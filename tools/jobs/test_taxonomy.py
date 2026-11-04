"""Tests for the jobs taxonomy. Run: python -m unittest discover tools/jobs"""

import unittest

from taxonomy import classify_location, is_data_engineering, level_of, min_years, names_other_country, skills_in, summary


class Titles(unittest.TestCase):
    def test_data_engineering_titles(self):
        for t in [
            "Data Engineer", "Senior Data Engineer, Risk", "Analytics Engineer – BI Platform",
            "Software Engineer, Data Platform", "ETL Developer", "Big Data Engineer", "Senior Data Ops engineer",
            "Staff Software Engineer (Data Platform)", "Snowflake Developer", "Data Engineer Intern",
            "Engineering Manager - Data Platform", "Consultant - Data Engineering",
        ]:
            self.assertTrue(is_data_engineering(t), t)

    def test_other_roles(self):
        for t in [
            "Data Scientist", "Senior Data Analyst", "Data Center Technician", "Machine Learning Engineer",
            "Product Manager - Data", "Senior Manager, Technical Program Management (Data Engineering)",
            "Specialist Solutions Architect - Data Engineering", "Data Engineering Solutions Specialist",
            "Senior Fullstack Engineer - Grafana Data Source Plugins", "Warehouse Associate",
            "Staff Security Engineer (Data Security Engineering)",
            "Field Robotics Engineer – Data Operations",
        ]:
            self.assertFalse(is_data_engineering(t), t)


class Locations(unittest.TestCase):
    def test_regions(self):
        self.assertEqual(classify_location("Bengaluru, Karnataka, India"), (["in"], False))
        self.assertEqual(classify_location("London, United Kingdom"), (["eu"], False))
        self.assertEqual(classify_location("Austin, TX"), (["na"], False))
        self.assertEqual(classify_location("US, Remote"), (["na"], True))
        self.assertEqual(classify_location("Remote"), ([], True))
        self.assertEqual(classify_location("Somewhere", country_codes=["DE"]), (["eu"], False))

    def test_word_boundaries_for_short_names(self):
        # "uk" inside a word isn't the UK.
        self.assertEqual(classify_location("Dukes Road")[0], [])

    def test_other_countries(self):
        self.assertTrue(names_other_country("São Paulo, Brazil"))
        self.assertTrue(names_other_country("Remote - APAC"))
        self.assertFalse(names_other_country("Remote - Europe"))


class Levels(unittest.TestCase):
    def test_levels(self):
        cases = {
            "Data Engineer Intern": "intern", "STAGE - Data Engineer F/H": "intern", "Werkstudent Data Engineering": "intern",
            "Head of Data Engineering": "manager", "Staff Data Engineer": "lead", "Senior Data Engineer": "senior",
            "Data Engineer I": "junior", "Junior Data Engineer": "junior", "Data Engineer": "mid",
        }
        for title, level in cases.items():
            self.assertEqual(level_of(title), level, title)

    def test_min_years(self):
        self.assertEqual(min_years("You have 3+ years of experience, ideally 5 years"), 3)
        self.assertEqual(min_years("2-4 years with Spark"), 2)
        self.assertIsNone(min_years("No experience needed"))
        self.assertIsNone(min_years("Founded 120 years ago"))


class Skills(unittest.TestCase):
    def test_skills(self):
        s = skills_in("Strong SQL and Python; PySpark on Databricks; dbt models; Airflow DAGs; Azure Data Factory")
        for k in ["sql", "python", "pyspark", "databricks", "dbt", "airflow", "azure"]:
            self.assertIn(k, s)
        self.assertNotIn("java", skills_in("JavaScript front end"))

    def test_summary_is_short(self):
        text = "word " * 200
        self.assertLessEqual(len(summary(text)), 221)
        self.assertTrue(summary(text).endswith("…"))


if __name__ == "__main__":
    unittest.main()
