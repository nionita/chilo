# Match-mode dependencies

Vendored headers require no installed libraries or runtime downloads:

- `json.hpp`: nlohmann/json v3.11.3, MIT (`json.LICENSE`).
- `picosha2.h`: okdshin/PicoSHA2 v1.0.1, MIT (license in header).

Downloaded header SHA-256 receipts:

```text
9bea4c8066ef4a1c206b2be5a36302f8926f7fdc6087af5d20b417d0cf103ea6  json.hpp
b13c180161ffac8d0adc81e033e493c409457c4d1258ab9781ac80579ba3bdd8  picosha2.h
```

`match_statistics.cpp` adapts the normalized likelihood algorithm from
Disservin/fastchess commit `072859b` (the installed fastchess 1.8.0 build).
Its MIT notice is retained in `fastchess.LICENSE`. The same revision's
`app/src/matchmaking/elo/elo_pentanomial.cpp` and match trackers are the
reference for reporting and adjudication semantics.
