#!/usr/bin/env python3
import sys
import unittest
from scraper import generate_job_id, local_pre_filter

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
            {"title": "Product Lead", "location": "San Francisco, CA"}
        ]
        
        keywords = ["Engineer", "Architect"]
        excludes = ["intern", "co-op"]
        
        # Test basic keyword filter and exclusions
        filtered = local_pre_filter(jobs, keywords, excludes)
        
        # Intern and Co-op should be excluded.
        # Product Lead should be excluded (does not match keywords).
        # Solutions Architect in California onsite should be excluded by "Florida Iron Curtain" geographic filter.
        # Only "Senior Python Engineer" in Orlando, FL should pass.
        self.assertEqual(len(filtered), 1)
        self.assertEqual(filtered[0]["title"], "Senior Python Engineer")

if __name__ == "__main__":
    unittest.main()
