# CHARLY CI-gates

De normale Top40Archiver pytest-suite blijft de primaire releasegate. `tests/test_charly_integration_contract.py` voegt CHARLY-specifieke controles toe voor versie, installer-syntax, vendorpakket, poorten, rollbackcontract en bescherming van de audiobibliotheek.

Een falende CHARLY-integratietest blokkeert de PR en daarmee de migratie naar `main`.
