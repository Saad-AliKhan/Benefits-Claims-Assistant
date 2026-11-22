"""Fake external systems (all data invented, in data/*.json):

    identity   pretends to be NADRA: a person by CNIC, or by name
    records    pretends to be the civil registration system (CRMS): death records
    payment    pretends to be a bank / Raast: accounts and transfers (ledger in the mock_transfers table)
    programme  the benefit programme's own list: income, dependants, already paid
    telco      pretends to be PTA / the operators: which CNIC a mobile number (SIM) is registered to

The claim flow calls the functions in api.py; routes.py offers the same thing over HTTP for /docs."""
