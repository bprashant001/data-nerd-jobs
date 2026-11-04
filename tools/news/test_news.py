"""Tests for the news pipeline. Run: python -m unittest discover -s tools/news"""

import unittest
from datetime import timezone

from fetch_news import excerpt, parse_feed, relevant, topics_for

RSS = b"""<?xml version="1.0"?><rss version="2.0"><channel>
<item><title>Delta Lake 5.0 &amp; more</title><link>https://example.com/a</link>
<description>&lt;p&gt;Faster MERGE for the lakehouse.&lt;/p&gt;</description>
<pubDate>Mon, 03 Nov 2026 10:00:00 GMT</pubDate></item>
</channel></rss>"""

ATOM = b"""<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom">
<entry><title>New agents API</title><link rel="alternate" href="https://example.com/b"/>
<summary>Build agents with tools.</summary><published>2026-11-02T08:00:00Z</published></entry>
</feed>"""


class Feeds(unittest.TestCase):
    def test_rss(self):
        [item] = parse_feed(RSS)
        self.assertEqual(item["title"], "Delta Lake 5.0 & more")
        self.assertEqual(item["link"], "https://example.com/a")
        self.assertEqual(item["summary"], "Faster MERGE for the lakehouse.")
        self.assertEqual(item["published"].tzinfo, timezone.utc)

    def test_atom(self):
        [item] = parse_feed(ATOM)
        self.assertEqual(item["link"], "https://example.com/b")
        self.assertEqual(item["published"].day, 2)


class Text(unittest.TestCase):
    def test_excerpt_is_short_and_drops_boilerplate(self):
        long = " ".join(["word"] * 100)
        self.assertLessEqual(len(excerpt(long).split()), 45)
        self.assertEqual(excerpt("A short intro. The post Foo appeared first on Bar."), "A short intro.")

    def test_excerpt_prefers_sentence_end(self):
        text = "First sentence is here and has some words in it. " * 3 + "tail " * 40
        self.assertTrue(excerpt(text).endswith("."))


class Topics(unittest.TestCase):
    def test_topics(self):
        self.assertEqual(topics_for("Faster Spark pipelines", "ai"), ["ai", "data"])
        self.assertEqual(topics_for("A new LLM release", "ai"), ["ai"])

    def test_relevance(self):
        self.assertTrue(relevant("Iceberg tables in BigQuery"))
        self.assertFalse(relevant("Our new office in Lisbon"))


if __name__ == "__main__":
    unittest.main()
