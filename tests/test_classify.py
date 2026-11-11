"""Page classification tests. URLs come from the Phase 1 overview output."""
import pytest

from tkb.classify import page_type, url_path


@pytest.mark.parametrize("url,expected", [
    ("https://www.dupaco.com/rates", "rate_sheet"),
    ("https://www.dupaco.com/business-rates/", "rate_sheet"),
    ("https://www.dupaco.com/personal/loans/auto-motorcycle-loans", "product"),
    ("https://www.dupaco.com/business/business-checking-accounts", "product"),
    ("https://www.dupaco.com/checking", "product"),
    # the bug found in Phase 1: business articles and tag pages are NOT products
    ("https://www.dupaco.com/business/resources/tag/cash-flow", "blog"),
    ("https://www.dupaco.com/business/resources/author/dupaco", "blog"),
    ("https://www.dupaco.com/business/resources/students-get-coaching-example", "blog"),
    ("https://www.dupaco.com/dupacodaily/2017/06/example-budgeting-article.html", "blog"),
    ("https://www.dupaco.com/2018/09/25/understand-insurance-deductibles", "blog"),
    ("https://www.dupaco.com/learn/blog/author/james-cyrus", "blog"),
    ("https://www.dupaco.com/newsroom/connecting-legislators-to-credit-union-impact", "press"),
    ("https://www.dupaco.com/calculators/vehicle-affordability", "calculator"),
    ("https://www.dupaco.com/business-calculators", "calculator"),
    ("https://www.dupaco.com/hubfs/break-even-template-dupaco.xlsx", "pdf"),
    ("https://www.dupaco.com/hubfs/example-fee-schedule.pdf", "pdf"),
    ("https://www.dupaco.com/switch-and-earn", "promo"),
    ("https://www.dupaco.com/checking-offer-lp", "promo"),
    ("https://www.dupaco.com/earn-more", "promo"),
    ("https://www.dupaco.com/contact", "other"),
])
def test_page_type(url, expected):
    assert page_type(url) == expected


def test_url_path_normalization():
    assert url_path("https://www.dupaco.com/Rates/#rates") == "/rates"   # case, trailing slash, fragment
    assert url_path("https://www.dupaco.com") == "/"
