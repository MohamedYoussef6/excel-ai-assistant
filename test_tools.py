"""
test_tools.py — Unit tests for all tool functions.

Run with:  python test_tools.py
All tests operate on COPIES of the Excel files so originals are never modified.
"""

import os
import sys
import shutil
import unittest
import pandas as pd

# ── Point tools at temp copies ────────────────────────────────────────────────
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
TEST_DIR  = os.path.join(BASE_DIR, "_test_data")

import tools  # import before patching paths

def _setup_test_files():
    os.makedirs(TEST_DIR, exist_ok=True)
    shutil.copy(
        os.path.join(BASE_DIR, "Real_Estate_Listings.xlsx"),
        os.path.join(TEST_DIR, "Real_Estate_Listings.xlsx"),
    )
    shutil.copy(
        os.path.join(BASE_DIR, "Marketing_Campaigns.xlsx"),
        os.path.join(TEST_DIR, "Marketing_Campaigns.xlsx"),
    )
    # Redirect tools to test copies
    tools.FILES["real_estate"] = os.path.join(TEST_DIR, "Real_Estate_Listings.xlsx")
    tools.FILES["marketing"]   = os.path.join(TEST_DIR, "Marketing_Campaigns.xlsx")

def _teardown_test_files():
    shutil.rmtree(TEST_DIR, ignore_errors=True)


# ═══════════════════════════════════════════════════════════════════════════════

class TestQueryData(unittest.TestCase):

    def test_query_all_rows(self):
        r = tools.query_data("real_estate", limit=10)
        self.assertEqual(len(r["rows"]), 10)
        self.assertIn("Listing ID", r["columns"])

    def test_query_with_eq_condition(self):
        r = tools.query_data("real_estate", conditions=[
            {"column": "State", "operator": "eq", "value": "Texas"}
        ])
        for row in r["rows"]:
            self.assertEqual(row["State"], "Texas")

    def test_query_with_gt_condition(self):
        r = tools.query_data("real_estate", conditions=[
            {"column": "List Price", "operator": "gt", "value": 1000000}
        ])
        for row in r["rows"]:
            self.assertGreater(row["List Price"], 1000000)

    def test_query_combined_conditions(self):
        r = tools.query_data("real_estate", conditions=[
            {"column": "Bedrooms",  "operator": "eq",  "value": 3},
            {"column": "State",     "operator": "eq",  "value": "California"},
            {"column": "List Price","operator": "lte", "value": 600000},
        ])
        for row in r["rows"]:
            self.assertEqual(row["Bedrooms"], 3)
            self.assertEqual(row["State"], "California")
            self.assertLessEqual(row["List Price"], 600000)

    def test_query_column_selection(self):
        r = tools.query_data("real_estate", columns=["Listing ID", "City"], limit=5)
        for row in r["rows"]:
            self.assertEqual(set(row.keys()), {"Listing ID", "City"})

    def test_query_order_by(self):
        r = tools.query_data("real_estate", order_by="List Price", ascending=False, limit=5)
        prices = [row["List Price"] for row in r["rows"]]
        self.assertEqual(prices, sorted(prices, reverse=True))

    def test_query_invalid_column_raises(self):
        with self.assertRaises(ValueError):
            tools.query_data("real_estate", conditions=[
                {"column": "NonExistent", "operator": "eq", "value": "X"}
            ])

    def test_query_marketing_contains(self):
        r = tools.query_data("marketing", conditions=[
            {"column": "Channel", "operator": "eq", "value": "Facebook"}
        ])
        for row in r["rows"]:
            self.assertEqual(row["Channel"], "Facebook")


class TestAggregateData(unittest.TestCase):

    def test_mean_list_price(self):
        r = tools.aggregate_data("real_estate", "mean", "List Price")
        self.assertIsInstance(r["result"], float)
        self.assertGreater(r["result"], 0)

    def test_count_all(self):
        r = tools.aggregate_data("real_estate", "count", "Listing ID")
        self.assertEqual(r["result"], 1000)

    def test_sum_with_filter(self):
        r = tools.aggregate_data("marketing", "sum", "Revenue Generated",
                                  conditions=[
                                      {"column": "Channel", "operator": "eq", "value": "Facebook"}
                                  ])
        self.assertIsInstance(r["result"], float)
        self.assertGreater(r["result"], 0)

    def test_group_by(self):
        r = tools.aggregate_data("real_estate", "mean", "List Price",
                                  group_by="Property Type")
        self.assertIsInstance(r["result"], dict)
        self.assertIn("House", r["result"])

    def test_invalid_metric_raises(self):
        with self.assertRaises(ValueError):
            tools.aggregate_data("real_estate", "variance", "List Price")

    def test_no_matching_rows(self):
        r = tools.aggregate_data("real_estate", "mean", "List Price",
                                  conditions=[
                                      {"column": "State", "operator": "eq", "value": "Hawaii"}
                                  ])
        self.assertIsNone(r["result"])


class TestInsertRow(unittest.TestCase):

    def test_insert_real_estate(self):
        initial = tools._load("real_estate")
        initial_count = len(initial)

        r = tools.insert_row("real_estate", {
            "Property Type":  "Condo",
            "City":           "Miami",
            "State":          "Florida",
            "Bedrooms":       2,
            "Bathrooms":      1.0,
            "Square Footage": 850,
            "Year Built":     2010,
            "List Price":     320000,
            "Sale Price":     None,
            "Listing Status": "Active",
        })
        self.assertEqual(r["new_row_count"], initial_count + 1)

        # Reload and verify
        df = tools._load("real_estate")
        last = df.iloc[-1]
        self.assertEqual(last["City"], "Miami")
        self.assertEqual(last["Bedrooms"], 2)

    def test_insert_auto_id_generated(self):
        r = tools.insert_row("real_estate", {"City": "Denver", "State": "Colorado"})
        self.assertIn("Listing ID", r["inserted"])
        self.assertTrue(r["inserted"]["Listing ID"].startswith("LST-"))

    def test_insert_marketing(self):
        r = tools.insert_row("marketing", {
            "Campaign Name":    "Test Campaign",
            "Channel":          "Email",
            "Start Date":       "2025-01-01",
            "End Date":         "2025-01-31",
            "Budget Allocated": 5000,
            "Amount Spent":     4800.0,
            "Impressions":      100000,
            "Clicks":           2500,
            "Conversions":      120,
            "Revenue Generated":15000.0,
        })
        self.assertIn("CMP-", r["inserted"]["Campaign ID"])


class TestUpdateRows(unittest.TestCase):

    def test_update_listing_status(self):
        # Get a real ID
        df = tools._load("real_estate")
        target_id = df.iloc[0]["Listing ID"]

        r = tools.update_rows(
            "real_estate",
            filters={"Listing ID": target_id},
            updates={"Listing Status": "Pending"},
        )
        self.assertEqual(r["rows_updated"], 1)

        # Verify
        df2 = tools._load("real_estate")
        row = df2[df2["Listing ID"] == target_id].iloc[0]
        self.assertEqual(row["Listing Status"], "Pending")

    def test_update_no_match(self):
        r = tools.update_rows(
            "real_estate",
            filters={"Listing ID": "LST-99999"},
            updates={"Listing Status": "Active"},
        )
        self.assertEqual(r["rows_updated"], 0)

    def test_update_invalid_column_raises(self):
        df = tools._load("real_estate")
        target_id = df.iloc[0]["Listing ID"]
        with self.assertRaises(ValueError):
            tools.update_rows(
                "real_estate",
                filters={"Listing ID": target_id},
                updates={"FakeColumn": "value"},
            )

    def test_bulk_update(self):
        r = tools.update_rows(
            "marketing",
            filters={"Channel": "Email"},
            updates={"Budget Allocated": 9999},
        )
        self.assertGreater(r["rows_updated"], 1)
        df = tools._load("marketing")
        email_rows = df[df["Channel"] == "Email"]
        self.assertTrue((email_rows["Budget Allocated"] == 9999).all())


class TestDeleteRows(unittest.TestCase):

    def test_delete_by_id(self):
        df = tools._load("real_estate")
        target_id = df.iloc[5]["Listing ID"]
        initial_count = len(df)

        r = tools.delete_rows("real_estate", filters={"Listing ID": target_id})
        self.assertEqual(r["rows_deleted"], 1)
        self.assertEqual(r["remaining_rows"], initial_count - 1)

        # Verify gone
        df2 = tools._load("real_estate")
        self.assertFalse((df2["Listing ID"] == target_id).any())

    def test_delete_no_match(self):
        r = tools.delete_rows("real_estate", filters={"Listing ID": "LST-00000"})
        self.assertEqual(r["rows_deleted"], 0)

    def test_delete_marketing(self):
        df = tools._load("marketing")
        target_id = df.iloc[0]["Campaign ID"]
        r = tools.delete_rows("marketing", filters={"Campaign ID": target_id})
        self.assertEqual(r["rows_deleted"], 1)


class TestGetSchema(unittest.TestCase):

    def test_schema_real_estate(self):
        r = tools.get_schema("real_estate")
        self.assertEqual(r["file"], "real_estate")
        self.assertIn("Listing ID", r["columns"])
        self.assertIn("List Price", r["columns"])
        self.assertGreater(r["row_count"], 0)

    def test_schema_marketing(self):
        r = tools.get_schema("marketing")
        self.assertIn("Channel", r["columns"])
        self.assertIn("Revenue Generated", r["columns"])


class TestDispatch(unittest.TestCase):

    def test_dispatch_valid(self):
        r = tools.dispatch("get_schema", {"file": "real_estate"})
        self.assertNotIn("error", r)

    def test_dispatch_unknown_tool(self):
        r = tools.dispatch("fly_to_moon", {})
        self.assertIn("error", r)

    def test_dispatch_bad_args(self):
        r = tools.dispatch("query_data", {"wrong_param": True})
        self.assertIn("error", r)


# ═══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("Setting up test environment...")
    _setup_test_files()
    try:
        loader = unittest.TestLoader()
        suite  = loader.loadTestsFromModule(sys.modules[__name__])
        runner = unittest.TextTestRunner(verbosity=2)
        result = runner.run(suite)
        exit_code = 0 if result.wasSuccessful() else 1
    finally:
        print("\nCleaning up test files...")
        _teardown_test_files()

    sys.exit(exit_code)
