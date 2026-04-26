#!/usr/bin/env python3
"""
Rejesha Journal — Automated Blog Post Generator
Runs daily at 9am CT via GitHub Actions.
Rotates through 4 pillars, generates SEO articles with Claude,
fetches Pixabay images, adds a Printify T-shirt widget, and publishes to Blogger.
"""

import os
import sys
import json
import random
import argparse
import requests
from datetime import datetime, timezone, timedelta

import anthropic
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build

# ── Config ────────────────────────────────────────────────────────────────────

PILLAR_ORDER = [
    "Immigration Reality",
    "Career & Money",
    "Finance & Stability",
    "Culture & Identity",
]

PILLAR_IMAGE_QUERIES = {
    "Immigration Reality":  "kenya nairobi africa travel diaspora",
    "Career & Money":       "african professional business office career",
    "Finance & Stability":  "african savings money home finance",
    "Culture & Identity":   "kenya africa community celebration culture",
}

PILLAR_LABELS = {
    "Immigration Reality":  ["Immigration Reality", "USCIS", "Visa", "Green Card"],
    "Career & Money":       ["Career & Money", "Jobs", "Salary", "Work"],
    "Finance & Stability":  ["Finance & Stability", "Credit", "Savings", "Real Estate"],
    "Culture & Identity":   ["Culture & Identity", "Kenyan Diaspora", "Identity", "Community"],
}

INTERNAL_LINKS = {
    "Immigration Reality":  "https://emyroyale254.blogspot.com/search/label/Immigration%20Reality",
    "Career & Money":       "https://emyroyale254.blogspot.com/search/label/Career%20%26%20Money",
    "Finance & Stability":  "https://emyroyale254.blogspot.com/search/label/Finance%20%26%20Stability",
    "Culture & Identity":   "https://emyroyale254.blogspot.com/search/label/Culture%20%26%20Identity",
}

STATE_FILE     = os.path.join(os.path.dirname(__file__), "state.json")
TOPICS_FILE    = os.path.join(os.path.dirname(__file__), "topics.json")

CT_OFFSET = timedelta(hours=-5)  # CDT; GitHub Actions handles DST via dual cron


# ── State Management ──────────────────────────────────────────────────────────

def load_state():
    with open(STATE_FILE, "r") as f:
        return json.load(f)

def save_state(state):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)

def load_topics():
    with open(TOPICS_FILE, "r") as f:
        return json.load(f)


def get_next_topic(state, topics):
    """Pick the next pillar and pop a topic from its remaining list."""
    pillar = PILLAR_ORDER[state["pillar_index"] % len(PILLAR_ORDER)]

    # Initialise remaining list on first run or if empty
    if not state["pillars"][pillar]["remaining"]:
        # Pull fresh list from topics.json, remove already used topics
        used = set(state["pillars"][pillar]["used"])
        fresh = [t for t in topics[pillar] if t not in used]

        # If everything has been used, reset and start over
        if not fresh:
            print(f"[{pillar}] All topics used — resetting pool.")
            state["pillars"][pillar]["used"] = []
            fresh = list(topics[pillar])

        random.shuffle(fresh)
        state["pillars"][pillar]["remaining"] = fresh

    topic = state["pillars"][pillar]["remaining"].pop(0)
    state["pillars"][pillar]["used"].append(topic)
    state["pillar_index"] += 1

    return pillar, topic


# ── Article Generation ────────────────────────────────────────────────────────

def generate_article(pillar, topic):
    """Call Claude to generate a full SEO-optimised HTML article."""
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

    other_pillars = [p for p in PILLAR_ORDER if p != pillar]
    internal_link_suggestions = "\n".join(
        f'- <a href="{INTERNAL_LINKS[p]}">Read more: {p}</a>' for p in other_pillars
    )

    system_prompt = """You are an expert SEO and GEO content writer for The Rejesha Journal,
a blog serving the Kenyan diaspora in America. Your writing is warm, authoritative, and deeply human.

STRICT OUTPUT RULES:
1. Return ONLY valid HTML — no markdown, no code fences, no explanations.
2. Do NOT include <html>, <head>, or <body> tags.
3. Start with an <h1> tag and end after the CTA section.
4. All links must be real, clickable HTML anchor tags — no placeholder text.

SEO REQUIREMENTS:
- Include the primary keyword/topic naturally in the H1 and within the first 100 words.
- Use one H1, four H2 subheadings, and H3s where helpful.
- Include a "Key Takeaways" <ul> box near the end.
- Meta description comment: <!-- META: [150-char description here] -->
- 3+ clickable external links to authoritative US government or nonprofit sources
  (USCIS.gov, IRS.gov, BLS.gov, SSA.gov, DHS.gov, consumerfinance.gov, usa.gov, etc.)
- 2+ internal links to other pillar pages (provided in the prompt).
- End with a call-to-action linking to https://rejesha.store

GEO SIGNALS (weave in naturally, not as a list):
Mention at least 3 of these US cities where Kenyans are concentrated:
Atlanta GA, Washington DC, New York NY, Dallas TX, Houston TX,
Minneapolis MN, Boston MA, Chicago IL, Seattle WA, San Jose CA.

TONE: First-person diaspora voice. Empathetic. Practical. Never preachy.
LENGTH: 1,200–1,500 words."""

    user_prompt = f"""Write a complete SEO-optimized blog post for The Rejesha Journal.

PILLAR: {pillar}
TOPIC: {topic}
BLOG: emyroyale254.blogspot.com

INTERNAL LINKS TO INCLUDE (use at least 2):
{internal_link_suggestions}

Write the full HTML article now."""

    print(f"[Claude] Generating article: '{topic}'...")
    response = client.messages.create(
        model="claude-opus-4-5",
        max_tokens=3000,
        system=system_prompt,
        messages=[{"role": "user", "content": user_prompt}],
    )

    content = response.content[0].text.strip()

    # Extract meta description if included
    meta = ""
    if "<!-- META:" in content:
        start = content.index("<!-- META:") + 10
        end   = content.index("-->", start)
        meta  = content[start:end].strip()
        content = content.replace(content[content.index("<!-- META:"):end+3], "").strip()

    # Extract title from H1
    title = topic
    if "<h1" in content:
        h1_start = content.index("<h1")
        h1_end   = content.index("</h1>") + 5
        raw_h1   = content[h1_start:h1_end]
        # Strip tags to get plain title
        import re
        title = re.sub(r"<[^>]+>", "", raw_h1).strip()

    return content, title, meta


# ── Pixabay Image ─────────────────────────────────────────────────────────────

def fetch_pixabay_image(pillar):
    """Fetch a relevant image from Pixabay and return image data."""
    key   = os.environ.get("PIXABAY_API_KEY", "")
    query = PILLAR_IMAGE_QUERIES[pillar]

    if not key:
        print("[Pixabay] No API key — skipping image.")
        return None

    try:
        resp = requests.get(
            "https://pixabay.com/api/",
            params={
                "key":          key,
                "q":            query,
                "image_type":   "photo",
                "orientation":  "horizontal",
                "per_page":     10,
                "safesearch":   "true",
                "min_width":    1000,
            },
            timeout=10,
        )
        resp.raise_for_status()
        hits = resp.json().get("hits", [])
        if not hits:
            return None

        photo     = random.choice(hits[:5])
        image_url = photo.get("largeImageURL") or photo.get("webformatURL")
        user_name = photo.get("user", "Pixabay")
        page_url  = photo.get("pageURL", "https://pixabay.com")

        print(f"[Pixabay] Image by {user_name}")
        return {
            "url":       image_url,
            "user_name": user_name,
            "page_url":  page_url,
        }

    except Exception as e:
        print(f"[Pixabay] Error: {e}")
        return None


# ── Printify Widget ───────────────────────────────────────────────────────────

def fetch_printify_product():
    """Fetch a random published product from Printify for the sidebar widget."""
    api_key = os.environ.get("PRINTIFY_API_KEY", "")
    shop_id = os.environ.get("PRINTIFY_SHOP_ID", "")

    if not api_key or not shop_id:
        print("[Printify] Missing credentials — skipping widget.")
        return None

    try:
        resp = requests.get(
            f"https://api.printify.com/v1/shops/{shop_id}/products.json",
            headers={"Authorization": f"Bearer {api_key}"},
            params={"limit": 20},
            timeout=10,
        )
        resp.raise_for_status()
        products = [p for p in resp.json().get("data", []) if p.get("visible", True)]

        if not products:
            return None

        product    = random.choice(products)
        title      = product["title"]
        handle     = product.get("external", {}).get("handle", "")
        images     = product.get("images", [])
        variants   = product.get("variants", [])
        image_src  = images[0]["src"] if images else ""
        price_cents = variants[0]["price"] if variants else 0
        price      = f"${price_cents / 100:.2f}"
        url        = f"https://rejesha.store/products/{handle}" if handle else "https://rejesha.store"

        print(f"[Printify] Widget: {title}")
        return {"title": title, "image": image_src, "price": price, "url": url}

    except Exception as e:
        print(f"[Printify] Error: {e}")
        return None


# ── HTML Assembly ─────────────────────────────────────────────────────────────

STYLES = """
<style>
/* Rejesha Journal article styles */
.rj-article-wrap { max-width: 740px; margin: 0 auto; font-family: 'Merriweather', Georgia, serif; color: #1a1a1a; line-height: 1.8; background: #fff; padding: 2.5rem 2rem; border-radius: 6px; box-shadow: 0 2px 24px rgba(0,0,0,0.18); }
.rj-cover-img { width: 100%; max-height: 460px; object-fit: cover; border-radius: 4px; margin-bottom: 1.5rem; }
.rj-article-wrap h1 { font-family: 'Playfair Display', Georgia, serif; font-size: 2.2rem; font-weight: 800; line-height: 1.2; margin-bottom: 1rem; color: #0a0a0a; }
.rj-article-wrap h2 { font-family: 'Playfair Display', Georgia, serif; font-size: 1.5rem; font-weight: 700; margin: 2rem 0 0.75rem; color: #111; }
.rj-article-wrap h3 { font-size: 1.1rem; font-weight: 700; margin: 1.5rem 0 0.5rem; color: #222; }
.rj-article-wrap p  { margin-bottom: 1.25rem; font-size: 1.05rem; }
.rj-article-wrap a  { color: #006631; text-decoration: underline; }
.rj-article-wrap a:hover { color: #C8001E; }
.rj-article-wrap ul, .rj-article-wrap ol { padding-left: 1.5rem; margin-bottom: 1.25rem; }
.rj-article-wrap li { margin-bottom: 0.5rem; font-size: 1.05rem; }
.rj-key-takeaways { background: #f8f5f0; border-left: 4px solid #006631; padding: 1.25rem 1.5rem; margin: 2rem 0; border-radius: 0 4px 4px 0; }
.rj-key-takeaways strong { display: block; font-family: 'Montserrat', sans-serif; font-size: 0.85rem; letter-spacing: 2px; text-transform: uppercase; color: #006631; margin-bottom: 0.75rem; }
.rj-cta-box { background: linear-gradient(135deg, #0a0a0a 0%, #1a1a1a 100%); color: #f5f0e8; padding: 2rem; border-radius: 4px; margin: 2.5rem 0; text-align: center; }
.rj-cta-box p { color: rgba(245,240,232,0.8); margin-bottom: 1rem; font-size: 1rem; }
.rj-cta-btn { display: inline-block; background: #006631; color: #fff !important; font-family: 'Montserrat', sans-serif; font-size: 0.85rem; font-weight: 700; letter-spacing: 2px; text-transform: uppercase; padding: 14px 32px; text-decoration: none !important; border-radius: 2px; }
.rj-pillar-tag { display: inline-block; font-family: 'Montserrat', sans-serif; font-size: 0.75rem; font-weight: 700; letter-spacing: 2px; text-transform: uppercase; color: #006631; border: 1px solid rgba(0,102,49,0.4); padding: 4px 12px; margin-bottom: 1.25rem; }
.rj-photo-credit { font-size: 0.8rem; color: #888; text-align: right; margin-top: -1rem; margin-bottom: 1.5rem; font-style: italic; }
.rj-photo-credit a { color: #888; }

/* Sidebar widget */
.rj-shop-widget { background: #0a0a0a; color: #f5f0e8; border-radius: 4px; overflow: hidden; margin: 1.5rem 0; font-family: 'Montserrat', sans-serif; }
.rj-widget-header { background: #006631; padding: 10px 16px; font-size: 10px; font-weight: 700; letter-spacing: 3px; text-transform: uppercase; color: #fff; }
.rj-widget-body { padding: 16px; }
.rj-widget-body img { width: 100%; border-radius: 2px; margin-bottom: 12px; }
.rj-widget-title { font-size: 0.9rem; font-weight: 600; color: #f5f0e8; margin-bottom: 6px; line-height: 1.4; }
.rj-widget-price { font-size: 1rem; font-weight: 700; color: #2db36e; margin-bottom: 14px; }
.rj-widget-btn { display: block; background: #C8001E; color: #fff !important; text-align: center; padding: 11px; font-size: 10px; font-weight: 700; letter-spacing: 2px; text-transform: uppercase; text-decoration: none !important; border-radius: 2px; }
.rj-widget-btn:hover { background: #a0001a; }
.rj-widget-browse { display: block; text-align: center; color: rgba(245,240,232,0.5) !important; font-size: 10px; letter-spacing: 1.5px; text-transform: uppercase; text-decoration: none !important; margin-top: 10px; }
</style>
"""

def build_html(article_html, image_data, product_data, pillar):
    """Assemble the full post HTML: styles + cover image + article + shop widget."""

    # Cover image block
    cover_html = ""
    if image_data:
        cover_html = f"""
<img class="rj-cover-img" src="{image_data['url']}" alt="{pillar} — The Rejesha Journal" loading="lazy">
<p class="rj-photo-credit">Photo by <a href="{image_data['page_url']}" target="_blank" rel="noopener">{image_data['user_name']}</a> via <a href="https://pixabay.com" target="_blank" rel="noopener">Pixabay</a></p>
"""

    # Pillar tag
    pillar_tag = f'<span class="rj-pillar-tag">{pillar}</span><br>'

    # Shop widget
    widget_html = ""
    if product_data:
        widget_html = f"""
<div class="rj-shop-widget">
  <div class="rj-widget-header">&#9733; Wear Your Roots</div>
  <div class="rj-widget-body">
    {"<img src='" + product_data['image'] + "' alt='" + product_data['title'] + "' loading='lazy'>" if product_data['image'] else ""}
    <div class="rj-widget-title">{product_data['title']}</div>
    <div class="rj-widget-price">{product_data['price']}</div>
    <a class="rj-widget-btn" href="{product_data['url']}" target="_blank">Shop Now &#8594;</a>
    <a class="rj-widget-browse" href="https://rejesha.store" target="_blank">Browse All Products</a>
  </div>
</div>
"""

    full_html = f"""{STYLES}
<div class="rj-article-wrap">
  {pillar_tag}
  {cover_html}
  {article_html}
  {widget_html}
</div>"""

    return full_html


# ── Blogger Publishing ────────────────────────────────────────────────────────

def publish_to_blogger(title, html, pillar):
    """Publish the post to Blogger via OAuth2 refresh token."""
    client_id     = os.environ.get("GOOGLE_CLIENT_ID", "")
    client_secret = os.environ.get("GOOGLE_CLIENT_SECRET", "")
    refresh_token = os.environ.get("GOOGLE_REFRESH_TOKEN", "")
    blog_id       = os.environ.get("BLOGGER_BLOG_ID", "")

    if not all([client_id, client_secret, refresh_token, blog_id]):
        print("[Blogger] Missing OAuth credentials — cannot publish.")
        return None

    credentials = Credentials(
        token=None,
        refresh_token=refresh_token,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=client_id,
        client_secret=client_secret,
        scopes=["https://www.googleapis.com/auth/blogger"],
    )
    # Force a token refresh before use
    credentials.refresh(Request())

    service = build("blogger", "v3", credentials=credentials)

    # Publish timestamp at 9am CT
    now_ct = datetime.now(timezone.utc) + CT_OFFSET
    publish_time = now_ct.replace(hour=9, minute=0, second=0, microsecond=0).isoformat()

    labels = PILLAR_LABELS.get(pillar, []) + ["Rejesha Journal", "Kenyan Diaspora"]

    post_body = {
        "title":     title,
        "content":   html,
        "labels":    list(set(labels)),
        "published": publish_time,
    }

    print(f"[Blogger] Publishing: '{title}'...")
    result = service.posts().insert(
        blogId=blog_id, body=post_body, isDraft=False
    ).execute()

    url = result.get("url", "")
    print(f"[Blogger] Published! URL: {url}")
    return url


# ── Main ──────────────────────────────────────────────────────────────────────

def main(dry_run=False):
    print("=" * 60)
    print("Rejesha Journal — Blog Post Generator")
    print(f"{'[DRY RUN] ' if dry_run else ''}Starting at {datetime.now().isoformat()}")
    print("=" * 60)

    # Load state and topics
    state  = load_state()
    topics = load_topics()

    # Get next pillar and topic
    pillar, topic = get_next_topic(state, topics)
    print(f"\nPillar : {pillar}")
    print(f"Topic  : {topic}\n")

    # Generate article
    article_html, title, meta = generate_article(pillar, topic)
    print(f"Title  : {title}")
    print(f"Meta   : {meta[:80] if meta else 'N/A'}")

    # Fetch image
    image_data = fetch_pixabay_image(pillar)

    # Fetch product widget
    product_data = fetch_printify_product()

    # Assemble HTML
    full_html = build_html(article_html, image_data, product_data, pillar)

    if dry_run:
        print("\n" + "=" * 60)
        print("[DRY RUN] Article HTML preview (first 1000 chars):")
        print("=" * 60)
        print(full_html[:1000])
        print("\n[DRY RUN] No post published. State not saved.")
        return

    # Publish
    url = publish_to_blogger(title, full_html, pillar)

    if url:
        # Save updated state
        state["last_run"] = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        save_state(state)
        print(f"\n[State] Saved. Pillar index now: {state['pillar_index']}")
        print("\n✓ Done!")
    else:
        print("\n✗ Publishing failed — state not saved.")
        sys.exit(1)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Rejesha Journal auto-post generator")
    parser.add_argument("--dry-run", action="store_true", help="Generate article but do not publish")
    args = parser.parse_args()
    main(dry_run=args.dry_run)
