from terkini.quotes import normalise, quote_in_text


def test_whitespace_differences_do_not_matter():
    page = "The tax rate is 8%\n for all   taxable services"
    assert quote_in_text("The tax rate is 8% for all taxable services", page)


def test_invented_quote_fails():
    page = "The tax rate is 8% for all taxable services"
    assert not quote_in_text("The tax rate is 6% for all taxable services", page)


def test_empty_quote_is_not_evidence():
    assert not quote_in_text("   ", "anything")


def test_normalise_trims():
    assert normalise("  a \t b\n") == "a b"
