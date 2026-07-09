# ---------- Importing All dependencies ----------
import asyncio
import json
import re
import warnings
from pathlib import Path
from playwright.async_api import async_playwright
from bs4 import BeautifulSoup, Tag
from camoufox.async_api import AsyncCamoufox

warnings.filterwarnings("ignore", category=UserWarning)


# ─── Fraction parsing ─────────────────────────────────────────────────────────
# Map unicode raw fractions → float for arithmetic

RAW_TO_FLOAT = {
    "½": 1/2,  "⅓": 1/3,  "⅔": 2/3,
    "¼": 1/4,  "¾": 3/4,
    "⅕": 1/5,  "⅖": 2/5,  "⅗": 3/5,  "⅘": 4/5,
    "⅙": 1/6,  "⅚": 5/6,
    "⅛": 1/8,  "⅜": 3/8,  "⅝": 5/8,  "⅞": 7/8,
}

# Map float → unicode raw fraction character (fractional part only)
FLOAT_TO_RAW = {v: k for k, v in RAW_TO_FLOAT.items()}
# Add a few extra tolerance entries for common results of scaling
FLOAT_TO_RAW.update({
    round(1/3, 10): "⅓",
    round(2/3, 10): "⅔",
    round(1/6, 10): "⅙",
    round(5/6, 10): "⅚",
})


def parse_qty(s: str):
    """Parse a quantity string (unicode fractions, slash fractions, whole numbers) → float, or None."""
    s = s.strip()
    if not s:
        return None
    if s in RAW_TO_FLOAT:
        return RAW_TO_FLOAT[s]
    total = 0.0
    for part in s.split():
        if part in RAW_TO_FLOAT:
            total += RAW_TO_FLOAT[part]
        elif "/" in part:
            try:
                n, d = part.split("/")
                total += float(n) / float(d)
            except Exception:
                return None
        else:
            try:
                total += float(part)
            except Exception:
                return None
    return total if total else None


def fmt_qty(v: float) -> str:
    """Convert float back to unicode raw fraction string (no decimals)."""
    if v is None or v == 0:
        return ""

    whole     = int(v)
    remainder = round(v - whole, 10)

    frac_char = ""
    for fval, char in FLOAT_TO_RAW.items():
        if abs(remainder - fval) < 0.005:
            frac_char = char
            break

    if whole and frac_char:
        return f"{whole} {frac_char}"
    if frac_char:
        return frac_char
    if whole:
        return str(whole)

    best_diff, best_char = min(
        ((abs(remainder - fv), ch) for fv, ch in FLOAT_TO_RAW.items()),
        key=lambda x: x[0]
    )
    return f"{whole} {best_char}" if whole else best_char


def scale_ingredient(raw: str, factor: float) -> str:
    """Scale leading quantity of an ingredient string by factor."""
    pattern = r"^([\d\s½⅓⅔¼¾⅕⅖⅗⅘⅙⅚⅛⅜⅝⅞\/]+)"
    m = re.match(pattern, raw.strip())
    if m:
        raw_qty = m.group(1).strip()
        rest    = raw[m.end():].lstrip()   # avoid double space
        qty     = parse_qty(raw_qty)
        if qty is not None:
            return f"{fmt_qty(qty * factor)} {rest}".strip()
    return raw


# ─── Duration helper ──────────────────────────────────────────────────────────

def parse_iso8601_duration(s: str) -> str:
    if not s:
        return ""
    m = re.match(r"PT(?:(\d+)H)?(?:(\d+)M)?", s)
    if not m:
        return s
    h    = int(m.group(1) or 0)
    mins = int(m.group(2) or 0)
    parts = []
    if h:    parts.append(f"{h} hr{'s' if h > 1 else ''}")
    if mins: parts.append(f"{mins} min{'s' if mins > 1 else ''}")
    return " ".join(parts) or s


# ─── JSON extraction ───────────────────────────────────────────────────────

def extract_jsonld_recipe(soup: BeautifulSoup) -> dict:
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(script.string or "")
        except Exception:
            continue
        blocks = data if isinstance(data, list) else [data]

        def find_recipe(obj):
            if not isinstance(obj, dict):
                return None
            types = obj.get("@type", "")
            if isinstance(types, str):
                types = [types]
            if "Recipe" in types:
                return obj
            for item in obj.get("@graph", []):
                r = find_recipe(item)
                if r:
                    return r
            return None

        for block in blocks:
            r = find_recipe(block)
            if r:
                return r
    return {}


# ─── HTML prose extraction ────────────────────────────────────────────────────

ARTICLE_SELECTORS = [
    "article",
    "[class*='recipe-content']",
    "[class*='recipe-body']",
    "[id*='recipe']",
    "main",
]

SKIP_TAGS = {
    "script", "style", "noscript", "meta", "head",
    "link", "svg", "iframe", "nav", "header", "footer",
}

SKIP_PATTERN = re.compile(
    r"(nav|header|footer|sidebar|breadcrumb|rating|review|comment|"
    r"advertisement|social|share|newsletter|popup|modal|related|"
    r"more-like|you-might|also-love|similar|saved-recipes|nutrition-label|"
    r"photo|gallery|carousel|video|promo|cookie|banner|signup|subscribe)",
    re.IGNORECASE,
)


def should_skip(el) -> bool:
    if not isinstance(el, Tag):
        return False
    if (el.name or "") in SKIP_TAGS:
        return True
    attrs = el.attrs or {}
    cls   = " ".join(attrs.get("class") or [])
    eid   = attrs.get("id") or ""
    return bool(SKIP_PATTERN.search(cls) or SKIP_PATTERN.search(eid))


def article_root(soup):
    for sel in ARTICLE_SELECTORS:
        el = soup.select_one(sel)
        if el:
            return el
    return soup.find("body") or soup


def clean(text: str) -> str:
    return " ".join(text.split()).strip()


def prune_junk(soup):
    targets = [el for el in soup.find_all(True) if should_skip(el)]
    for el in targets:
        try:
            el.decompose()
        except Exception:
            pass


def extract_prose(soup: BeautifulSoup) -> list:
    """Extract (heading, paragraph) pairs after pruning junk."""
    prune_junk(soup)
    root     = article_root(soup)
    sections = []
    head     = ""
    buf      = []

    def flush():
        nonlocal buf, head
        t = " ".join(buf).strip()
        if t:
            sections.append((head, t))
        buf = []

    for el in list(root.find_all(True)):
        if not isinstance(el, Tag):
            continue
        name = el.name or ""
        if name in ("script", "style", "noscript"):
            continue
        if name in ("h1", "h2", "h3", "h4"):
            t = clean(el.get_text())
            if t:
                flush()
                head = t
        elif name == "p":
            t = clean(el.get_text())
            if t and len(t) > 30:
                buf.append(t)
        elif name == "li":
            parent = el.parent.name if el.parent else ""
            if parent in ("ul", "ol"):
                t = clean(el.get_text())
                if t and len(t) > 15:
                    buf.append(t)
    flush()
    return sections


def extract_all_content(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    prune_junk(soup)
    body = soup.find("body") or soup
    lines = [clean(line) for line in body.get_text(separator="\n").splitlines() if clean(line)]
    return "\n".join(lines)


# ─── Ingredient scaling block ─────────────────────────────────────────────────

def build_scaling_block(ingredients: list) -> str:
    lines = []
    for label, factor in [("½x", 0.5), ("1x", 1.0), ("2x", 2.0)]:
        lines.append(f"\n  [{label}]")
        for ing in ingredients:
            raw = ing.strip()
            if factor == 1.0:
                lines.append(f"    - {raw}")
            else:
                lines.append(f"    - {scale_ingredient(raw, factor)}")
    return "\n".join(lines)


# ─── Nutrition formatter ──────────────────────────────────────────────────────

def format_nutrition(n: dict) -> str:
    if not n:
        return ""
    fields = [
        ("calories",            "Calories"),
        ("fatContent",          "Fat"),
        ("saturatedFatContent", "Saturated Fat"),
        ("carbohydrateContent", "Carbs"),
        ("sugarContent",        "Sugar"),
        ("fiberContent",        "Fiber"),
        ("proteinContent",      "Protein"),
        ("sodiumContent",       "Sodium"),
        ("cholesterolContent",  "Cholesterol"),
    ]
    return " | ".join(f"{lbl}: {n[k]}" for k, lbl in fields if n.get(k))


# ─── Output assembler ─────────────────────────────────────────────────────────

SKIP_PROSE_HEADS = re.compile(
    r"(ingredient|direction|instruction|step|nutrition|review|comment|"
    r"photo|rating|related|similar|you (might|may)|also love|save)",
    re.IGNORECASE,
)


def assemble(recipe: dict, prose: list) -> str:
    out = []

    def add(line=""):
        out.append(line)

    title = clean(recipe.get("name", ""))
    if title:
        add("=" * 60)
        add(f"  {title.upper()}")
        add("=" * 60)

    meta = []
    prep  = parse_iso8601_duration(recipe.get("prepTime",  ""))
    cook  = parse_iso8601_duration(recipe.get("cookTime",  ""))
    total = parse_iso8601_duration(recipe.get("totalTime", ""))
    yld   = recipe.get("recipeYield", "")
    if isinstance(yld, list):
        yld = ", ".join(str(y) for y in yld)
    if prep:  meta.append(f"Prep: {prep}")
    if cook:  meta.append(f"Cook: {cook}")
    if total: meta.append(f"Total: {total}")
    if yld:   meta.append(f"Servings: {yld}")
    if meta:
        add("  " + "  |  ".join(meta))
        add()

    desc = clean(recipe.get("description", ""))
    if desc:
        add("DESCRIPTION")
        add("-" * 40)
        add(desc)
        add()

    for heading, paragraph in prose:
        if SKIP_PROSE_HEADS.search(heading) or SKIP_PROSE_HEADS.search(paragraph[:80]):
            continue
        if heading:
            add(heading.upper())
            add("-" * 40)
        add(paragraph)
        add()

    ingredients = recipe.get("recipeIngredient", [])
    if ingredients:
        add("INGREDIENTS")
        add("-" * 40)
        add(build_scaling_block(ingredients))
        add()

    instructions = recipe.get("recipeInstructions", [])
    if instructions:
        add("DIRECTIONS")
        add("-" * 40)
        step = 1
        for item in instructions:
            if isinstance(item, str):
                t = clean(item)
                if t:
                    add(f"{step}. {t}")
                    step += 1
            elif isinstance(item, dict):
                if item.get("@type") == "HowToSection":
                    sec = clean(item.get("name", ""))
                    if sec:
                        add(f"\n  [{sec}]")
                    for sub in item.get("itemListElement", []):
                        t = clean(sub.get("text", ""))
                        if t:
                            add(f"  {step}. {t}")
                            step += 1
                else:
                    t = clean(item.get("text", ""))
                    if t:
                        add(f"{step}. {t}")
                        step += 1
        add()

    nut = format_nutrition(recipe.get("nutrition", {}))
    if nut:
        add("NUTRITION  (per serving)")
        add("-" * 40)
        add(nut)
        add()

    keywords = recipe.get("keywords",       "")
    category = recipe.get("recipeCategory", "")
    cuisine  = recipe.get("recipeCuisine",  "")
    if isinstance(keywords, list):
        keywords = ", ".join(keywords)
    info = []
    if category: info.append(f"Category: {clean(str(category))}")
    if cuisine:  info.append(f"Cuisine:  {clean(str(cuisine))}")
    if keywords: info.append(f"Tags:     {clean(keywords)}")
    if info:
        add("INFO")
        add("-" * 40)
        for line in info:
            add(line)
        add()

    return "\n".join(out)


# ─── Camoufox fetcher ───────────────────────────────────

async def fetch_html_camoufox(url: str) -> str:
    """Fetch HTML using Playwright Chromium (avoids Firefox pageerror crash)."""
    html = None
    browser = None
    page = None

    try:
        playwright = await async_playwright().start()
        browser = await playwright.chromium.launch(
            headless=True,
            args=[
                "--disable-gpu",
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--disable-blink-features=AutomationControlled",  # hide automation
            ]
        )
        context = await browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1920, "height": 1080},
        )
        page = await context.new_page()

        # Still good practice to keep this handler
        page.on("pageerror", lambda err: print(f"⚠️ Page JS error (ignored): {err}"))

        await page.goto(url, wait_until="domcontentloaded", timeout=60000)
        await page.wait_for_timeout(4000)
        html = await page.content()

        await browser.close()
    except Exception as exc:
        print(f"💥 Playwright fetch failed: {exc}")
        if browser:
            try:
                await browser.close()
            except:
                pass

    return html or ""


# ─── Main scraper ─────────────────────────────────────────────────────────────

async def scrape_recipe(url: str, save_path: str = "scraped_recipe.txt", save_html_path: str = None) -> str:
    print(f"🚀 Starting  →  {url}")
    html = await fetch_html_camoufox(url)
    if not html:
        print("❌ No HTML — aborting.")
        return ""

    soup = BeautifulSoup(html, "html.parser")
    recipe = extract_jsonld_recipe(soup)
    if not recipe:
        print("⚠️  No JSON-LD Recipe schema found — output may be incomplete.")

    prose  = extract_prose(soup)
    output = assemble(recipe, prose)

    if not output.strip():
        print("ℹ️ No structured recipe output found — falling back to full-text extraction.")
        output = extract_all_content(html)

    if save_html_path:
        try:
            Path(save_html_path).write_text(html, encoding="utf-8")
        except Exception:
            pass

    if save_path:
        try:
            Path(save_path).write_text(output, encoding="utf-8")
            print(f"💾 Saved → '{save_path}'")
        except Exception:
            pass

    return output