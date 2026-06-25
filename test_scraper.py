#!/usr/bin/env python3
import sys
import unittest
from scraper import generate_job_id, local_pre_filter, group_candidate_criteria

class TestScraperHeuristics(unittest.TestCase):
    
    def test_generate_job_id(self):
        id1 = generate_job_id("Software Engineer", "Google")
        id2 = generate_job_id("Software Engineer", "Google")
        id3 = generate_job_id("Product Manager", "Google")
        
        self.assertEqual(id1, id2)
        self.assertNotEqual(id1, id3)
        self.assertEqual(len(id1), 32) # MD5 hex digest length

    def test_local_pre_filter(self):
        jobs = [
            {"title": "Senior Python Engineer", "location": "Orlando, FL"},
            {"title": "Software Engineer Intern", "location": "Remote"},
            {"title": "Software Engineer Co-op", "location": "Florida, US"},
            {"title": "Solutions Architect", "location": "California"},
            {"title": "Product Lead", "location": "San Francisco, CA"},
            {"title": "Senior Solutions Architect", "location": "Toronto, Ontario, Canada"},
            {"title": "Lead Software Architect", "location": "Minneapolis, MN"},
            {"title": "Scrum Master", "location": "Toronto, ON"}
        ]
        
        keywords = ["Engineer", "Architect", "Master"]
        excludes = ["intern", "co-op"]
        
        # Test basic keyword filter and exclusions
        filtered = local_pre_filter(jobs, keywords, excludes)
        
        # Intern and Co-op should be excluded.
        # Product Lead should be excluded (does not match keywords).
        # California, Toronto, and Minneapolis onsite jobs should be excluded by "Florida Iron Curtain" geographic filter.
        # Only "Senior Python Engineer" in Orlando, FL should pass.
        self.assertEqual(len(filtered), 1)
        self.assertEqual(filtered[0]["title"], "Senior Python Engineer")

    def test_group_candidate_criteria(self):
        sources = [
            {
                "Organization": "Org1",
                "Target Keywords": "project manager, scrum master",
                "Exclude Keywords": "developer, programmer",
                "Sector Tag": "Rachel"
            },
            {
                "Organization": "Org2",
                "Target Keywords": "data analyst, bi",
                "Exclude Keywords": "accountant",
                "Sector Tag": "Greg"
            },
            {
                "Organization": "Org3",
                "Target Keywords": "agile",
                "Exclude Keywords": "qa",
                "Sector Tag": "Rachel"
            }
        ]
        
        kws, exs = group_candidate_criteria(sources)
        
        # Rachel's grouped keywords and excludes
        self.assertIn("project manager", kws["Rachel"])
        self.assertIn("scrum master", kws["Rachel"])
        self.assertIn("agile", kws["Rachel"])
        self.assertNotIn("data analyst", kws["Rachel"])
        self.assertIn("developer", exs["Rachel"])
        self.assertIn("programmer", exs["Rachel"])
        self.assertIn("qa", exs["Rachel"])
        
        # Greg's grouped keywords and excludes
        self.assertIn("data analyst", kws["Greg"])
        self.assertIn("bi", kws["Greg"])
        self.assertIn("accountant", exs["Greg"])
        self.assertNotIn("project manager", kws["Greg"])

if __name__ == "__main__":
    unittest.main()
