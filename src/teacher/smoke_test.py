"""Quick connectivity check for the Teacher pipeline.

Run after Notion DB creation and config_teacher.yaml edits, before flipping
the workflow live. Tests each stage in isolation:

  python src/teacher/smoke_test.py [stage]

Stages: notion | blogs | x | inbox | curate | script | all
"""

import os
import sys
from pathlib import Path

import yaml

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))


def load_cfg():
    p = Path(__file__).resolve().parent.parent.parent / "config_teacher.yaml"
    with open(p) as f:
        return yaml.safe_load(f) or {}


def test_notion(cfg):
    from notion_dbs import get_client, ensure_all_schemas
    notion = get_client()
    if not notion:
        print("✗ NOTION_TOKEN not set")
        return False
    notion_cfg = cfg.get("notion") or {}
    missing = [k for k in ("curriculum_db_id", "sources_db_id", "episodes_db_id", "inbox_db_id") if not notion_cfg.get(k)]
    if missing:
        print(f"✗ Missing Notion DB IDs in config_teacher.yaml: {missing}")
        return False
    ensure_all_schemas(notion, notion_cfg)
    print("✓ Notion connectivity + schema OK")
    return True


def test_blogs(cfg):
    from discover_web import discover_blog_sources
    sources = cfg.get("blog_sources", [])[:3]  # First 3 only for speed
    items = discover_blog_sources(sources, lookback_days=14, max_items_per_blog=2)
    print(f"✓ Blog discovery: {len(items)} item(s) from {len(sources)} feed(s)")
    if items:
        sample = items[0]
        print(f"  Sample: {sample['source']} — {sample['title'][:80]}")
        print(f"  Full text length: {len(sample.get('full_text', ''))} chars")
    return len(items) > 0


def test_x(cfg):
    from discover_x import discover_x_handles
    handles = cfg.get("x_handles", [])[:2]  # First 2 handles only
    items = discover_x_handles(handles, max_items_per_handle=1, lesson_topic="AI for marketing")
    print(f"✓ X discovery: {len(items)} post(s) from {len(handles)} handle(s)")
    if items:
        print(f"  Sample: {items[0]['source']} — {items[0]['title'][:80]}")
    return True  # X discovery is best-effort — empty isn't a failure


def test_inbox(cfg):
    from notion_dbs import get_client
    from discover_inbox import discover_inbox
    notion = get_client()
    items = discover_inbox(notion, (cfg.get("notion") or {}).get("inbox_db_id", ""), max_items=5)
    print(f"✓ Inbox discovery: {len(items)} item(s)")
    return True


def test_curate(cfg):
    from discover_web import discover_blog_sources
    from curate import curate
    items = discover_blog_sources(cfg.get("blog_sources", [])[:3], lookback_days=14, max_items_per_blog=2)
    if not items:
        print("✗ No items to curate")
        return False
    lesson = {"topic": "RAG for brand voice", "lesson_num": 5, "is_foundational": True, "gaps": "", "hypothesis": ""}
    top = curate(items, lesson, target_count=3)
    print(f"✓ Curated {len(top)} of {len(items)} items")
    return True


def test_script(cfg):
    from lesson_script import generate_lesson_script
    fake_curated = [
        {
            "title": "Test source about RAG",
            "url": "https://example.com/test",
            "author": "Test Author",
            "source": "Test Source",
            "source_type": "Blog",
            "source_tier": "Practitioner",
            "key_claims": ["Test claim 1", "Test claim 2"],
            "quotes": [{"text": "Sample quote", "context": "Sample context"}],
            "brand_implication": "Test implication for brand work",
            "mechanic_summary": "Test mechanic summary",
            "one_line_take": "Teaches the test concept",
        }
    ]
    lesson = {"topic": "RAG for brand voice", "lesson_num": 5, "is_foundational": True, "gaps": "", "hypothesis": ""}
    script, prompts = generate_lesson_script(lesson, fake_curated, word_budget=(800, 1200))
    word_count = len(script.split())
    print(f"✓ Lesson script: {word_count} words, {len(prompts)} follow-up prompt(s)")
    print(f"  First 200 chars: {script[:200]}")
    return word_count > 200


STAGES = {
    "notion": test_notion,
    "blogs": test_blogs,
    "x": test_x,
    "inbox": test_inbox,
    "curate": test_curate,
    "script": test_script,
}


def main():
    cfg = load_cfg()
    stage = sys.argv[1] if len(sys.argv) > 1 else "all"
    if stage == "all":
        order = ["notion", "blogs", "x", "inbox", "curate", "script"]
        results = {}
        for s in order:
            print(f"\n— {s} —")
            try:
                results[s] = STAGES[s](cfg)
            except Exception as e:
                print(f"✗ {s} crashed: {e}")
                results[s] = False
        print("\nSummary:")
        for s, ok in results.items():
            print(f"  {'✓' if ok else '✗'} {s}")
        return 0 if all(results.values()) else 1
    elif stage in STAGES:
        ok = STAGES[stage](cfg)
        return 0 if ok else 1
    else:
        print(f"Unknown stage: {stage}. Valid: {list(STAGES) + ['all']}")
        return 2


if __name__ == "__main__":
    sys.exit(main())
