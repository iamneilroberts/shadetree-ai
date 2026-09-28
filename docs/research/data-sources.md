# Reference data sources for the OBD assistant (research 2026-09-28)

Not legal advice. Public pages only; nothing logged into, scraped, or installed. Web fetch was blocked (403/TLS) on several primary pages (NHTSA datasets page, AutoZone terms, Toyota TIS legal page); those claims rest on search-result excerpts and are marked. Prices from forums or aggregators are dated and approximate.

Confidence tags map to design §8: `authoritative | curated | community | provenance_unknown | model_drafted`.

## 1. Summary table

| Source | Covers (a-f) | Access | Price | Automated use / caching / AI | Tag |
|---|---|---|---|---|---|
| NHTSA vPIC | f (VIN 1980+) | API + offline DB | free | no license/registration needed | authoritative |
| NHTSA recalls + complaints APIs | d | API, no key | free | public gov data; terms text not read | authoritative |
| NHTSA MfrComms (TSB summaries) | d | flat file since 1995 | free | public gov data; not full TSB text | authoritative |
| fueleconomy.gov | e (specs, 1984+) | REST + CSV | free | no terms documented on page | authoritative |
| fabiovila / Wal33D / lennykean DTC lists | a | GitHub | free | MIT, provenance unstated | provenance_unknown |
| OBDb + OBDb/SAEJ1979 | b | GitHub | free | CC BY-SA 4.0 | community |
| opendbc | b (CAN, 2016+) | GitHub | free | MIT | community |
| Wikipedia OBD-II PIDs, Wikibooks | b, c | web/dump | free | CC BY-SA | curated (PIDs), community (Wikibooks) |
| HF karsonmadden/us-vehicle-trouble-codes | a, d | download | free | CC BY 4.0 | community |
| Operation CHARM | c, e | web / 700GB dump | free | almost certainly infringing | AVOID |
| AutoZone / OBD-Codes.com / RepairPal / CarComplaints | a, c, d | web | free | ToS restrict automation | do not ingest |
| ChiltonLibrary (library card) | c, e | web | free with card | Gale ToS bans AI use | human-read only |
| ALLDATA DIY | c, d, e | web login | $19.99/mo, $59.99/yr, $129.99/3yr | ToS bans robots, storage, derivatives | human-read only |
| OEM sites (Toyota, Honda, Ford, GM...) | c, e | login | $20-$1,500 by term | not verified; assume no | human-read only |
| CarAPI | a, f | API | $199-$299/yr | caching explicitly allowed | provenance_unknown |

## 2. Government / open data

**NHTSA vPIC.** VIN decode with 50-VIN batch, all endpoints XML/CSV/JSON, VINs from 1980 on, standalone offline database downloadable ([vpic.nhtsa.dot.gov/api](https://vpic.nhtsa.dot.gov/api/)). The FAQ states there is no licensing or registration requirement ([catalog.data.gov summary](https://catalog.data.gov/dataset/nhtsa-product-information-catalog-and-vehicle-listing-vpic-vehicle-api-json)). Rate limit thresholds are undocumented. Pre-2008 strength: good for make/model/year/engine basics; detail fields depend on manufacturer submissions and are thinner for old cars (my inference, unverified). Tag: authoritative.

**NHTSA recalls and complaints.** `api.nhtsa.gov/recalls/recallsByVehicle` and `/complaints/complaintsByVehicle` take make/model/modelYear; no key ([NHTSA dataset listing, via search](https://www.nhtsa.gov/nhtsa-datasets-and-apis)). Complaints go back decades, so useful for pre-2008 cars. Tag: authoritative (recalls); complaints are unverified consumer text, so `community`-grade for any failure-pattern claim.

**MfrComms.txt (TSB/manufacturer communications).** Tab-delimited, communications received since 1 Jan 1995, renamed from TSBS.txt on 3 May 2024 ([field layout](https://static.nhtsa.gov/nhtsa/downloads/Temp/MfrComms.txt), [flat-file page](https://www-odi.nhtsa.dot.gov/downloads/flatfiles.cfm)). It carries summaries, not full repair procedures (per design §8; I could not open the file). Good for "known-issue exists" pointers by make/model/year. Tag: authoritative for existence, and the summary text is the manufacturer's own.

**fueleconomy.gov.** REST plus zipped CSV of all vehicles, 1984 to present ([web services](https://www.fueleconomy.gov/ws/), [download](https://www.fueleconomy.gov/feg/download.shtml)). Engine size, cylinders, transmission. No usage terms appear on the docs page. Tag: authoritative (specs only, no test values).

**CARB/EPA OBD regs.** 13 CCR 1968.2 and 40 CFR 86.1806-17 are free, but they specify monitor requirements, not per-code text ([Cornell LII](https://www.law.cornell.edu/regulations/california/13-CCR-1968.2)). The regs reference SAE J2012 code definitions rather than reproduce them. Use for OBD monitor/readiness rules only. SAE J2012/J1979 themselves are paid (design §8).

**Not government but adjacent:** DMCA 1201 exemption for vehicle diagnosis/repair runs to 28 Oct 2027 ([Auto Care](https://www.autocare.org/detail-pages/blog/aina/2024/11/01/new-exemption-to-digital-millennium-copyright-act-broadens-protection-for-vehicle-data-access)). It covers circumventing access controls on vehicle software; it does not license copying repair-manual text.

## 3. Open-license datasets and projects

- **fabiovila/OBDIICodes**: JSON + C header of generic codes ([repo](https://github.com/fabiovila/OBDIICodes)). Design §8 records MIT and 2,381 codes; I could not confirm the license text this session. Provenance unstated. Tag: provenance_unknown.
- **Wal33D/dtc-database**: MIT, SQLite, claims 9,415 generic + 9,390 manufacturer-specific across 33+ brands built from 37 "CODE - Description" text files; the page does not name where those came from ([repo](https://github.com/Wal33D/dtc-database/)). MIT on the repo does not cure unknown upstream provenance. Only source for manufacturer-specific coverage in bulk. Tag: provenance_unknown.
- **lennykean/OBDII.DTC**: MIT, generic codes "based on" ISO 15031 and SAE J2012 ([repo](https://github.com/lennykean/OBDII.DTC)). The descriptions likely trace to SAE text, so provenance risk is the same.
- **OBDb**: CC BY-SA 4.0, 746+ per-vehicle repos, `signalsets/v3/default.json` plus year overrides; example vehicles are modern (Toyota Venza/RAV4, Mazda CX-5, Mercedes E-Class) ([org](https://github.com/OBDb)). **OBDb/SAEJ1979** is CC BY-SA 4.0 PIDs only, no DTCs ([repo](https://github.com/OBDb/SAEJ1979)). ShareAlike applies to derived data: keep as a separate source, do not merge into hand-written records.
- **opendbc**: MIT, DBC files for CAN messages (cars with LKAS/ACC since ~2016) ([repo](https://github.com/commaai/opendbc)). Not OBD-II PIDs. Low value for 1996-2008 cars.
- **python-OBD**: GPL-2.0+ per design §8 (not re-checked). Do not copy tables.
- **Wikipedia OBD-II PIDs**: CC BY-SA 4.0 ([page](https://en.wikipedia.org/wiki/OBD-II_PIDs)). Write your own table from these public facts and attribute if you copy text.
- **Wikibooks Automobile Repair**: CC BY-SA ([book](https://en.wikibooks.org/wiki/Automobile_Repair/Diagnostics)). Thin and generic; quality unaudited. Tag: community.
- **HF karsonmadden/us-vehicle-trouble-codes**: CC BY 4.0, 1,142 codes with bulletin counts and NHTSA complaint counts, regenerated nightly by WhichTrim; only 119 (10.4%) have meanings ([dataset](https://huggingface.co/datasets/karsonmadden/us-vehicle-trouble-codes)). Useful as a "which codes show up in real TSBs/complaints" prior; we can rebuild the same from NHTSA directly.
- Other HF/Kaggle sets exist ([Epitech/obd-codes-fine-tune](https://huggingface.co/datasets/Epitech/obd-codes-fine-tune), [Kaggle OBD2 powertrain codes](https://www.kaggle.com/datasets/donnetew/odb2-powertrain-codes)); I did not read their licenses or provenance.

## 4. Free-to-read but copyrighted

| Source | What ToS says (verified by) | Practical risk |
|---|---|---|
| **Operation CHARM** (charm.li) | 1982-2013 manuals, 50,000+ models, code/DB released, 700GB p2p dump ([search excerpt](https://charm.li/)). Legal status is not stated on the pages I could reach. HN commenters call it pirated ALLDATA/Bentley copies ([HN](https://news.ycombinator.com/item?id=40409588)); that is opinion, but I found no license grant either. No takedown found, none ruled out. | High. Ingesting and redistributing would import likely-infringing text into our store. Avoid. |
| **AutoZone repair guides** | AutoZone terms prohibit "spider, robot, cheat utility, scraper, or offline reader" ([search excerpt of terms](https://www.autozone.com/lp/termsAndConditions)); page itself returned 403. Guides need a Rewards login per search snippet. | Do not scrape. Human reading fine. |
| **OBD-Codes.com** | Site says all content is copyright protected ([site](https://www.obd-codes.com/trouble_codes/)); no separate ToS found. | Read, don't copy. Paraphrase risk is low, bulk copy is not. |
| **RepairPal** | Bans robots/spiders exceeding human request rates and copying "any part of the Service" ([ToS](https://repairpal.com/terms_of_service)). Has a partner API, terms not public ([partners](https://pages.repairpal.com/partners)). | Do not ingest. Its value is cost estimates, not diagnostics. |
| **CarComplaints** | Copyright by Autobeef; commercial use of RSS/content prohibited without written agreement ([ToS](https://tostracker.app/document/carcomplaints)). Actively fights real-time scrapers. | Link out only. NHTSA complaints give the same signal free. |
| **YouTube transcripts** | ToS bars automated access without permission; transcript libraries hit technically public endpoints, tolerated at low volume ([ScrapeOps](https://scrapeops.io/websites/youtube/)). Creator copyright remains. | Medium. Use as human lead-generation for playbook ideas, never ingest. |
| **Reddit** | Scraping needs written consent; ML training on API data needs separate license; commercial API reported from ~$12k/mo ([summary](https://prowlo.com/blog/reddit-data-api), secondary source). | Skip for the store. |
| **iATN** | Free tier for qualified pros (4 yrs experience or ASE); Individual $19/mo unlocks Knowledge Base ([pricing](https://www.iatn.net/pricing), [free tier](https://www.aa1car.com/library/iatn.htm)). No AI/automation terms found. Austin might qualify. | Human use only; its FIX database is the best real-world "what fixed it" resource I found, so a human-in-loop use by Austin is the sensible path. |

## 5. Paid / credentialed professional sources

| Source | Price found | Coverage | Automation/caching/AI (as read) |
|---|---|---|---|
| **ALLDATA DIY** | $19.99 / 1 mo, $59.99 / 1 yr, $129.99 / 3 yr, one vehicle; 30,000+ vehicles 1982-2021; wiring, TSBs, DTC, recalls ([plans](https://www.alldata.com/diy-us/en/diy-repair-information)) | Strong pre-2008 | Bans spider/robot/automatic device or manual copying; no storage in retrieval systems; no derivative works; no AI mention ([ToS 2025](https://www.alldata.com/diy-us/en/terms-and-conditions-2025)). Clear no. |
| **Mitchell 1 DIY / ProDemand** | DIY "from $19.99" ([search summary](https://eautorepair.net/marketingpages/product.html)); ProDemand pro pricing not found | Strong | Materials may not be copied, distributed or republished; one personal copy allowed ([legal notices](https://mitchell1.com/legal-notices/)). Automation not named but not permitted by the copying clause. |
| **Identifix Direct-Hit** | DIY $24.99/mo single model; Pro $199/mo ([Tekpon/TrustRadius aggregators](https://tekpon.com/software/identifix/reviews/)) | Fix-frequency database from tech reports | ToS not read. Assume no. |
| **Haynes Pro** | ~$149.99/yr claimed on a reseller wiki ([AliExpress article](https://www.aliexpress.com/s/wiki-ssr/article/haynes-pro-subscription-price)); unreliable | 12,000+ vehicles claimed | ToS not read. |
| **ChiltonLibrary via library card** | Free with card at many public libraries ([Great River](https://griver.org/library-news/chilton-is-back), [Austin PL](https://library.austintexas.gov/digital/chilton-library)); step-by-step, wiring, TSBs; "past 30 years plus specialty" ([Gale](https://www.gale.com/c/chilton-library)) | Good for 1996-2008 | Gale prohibits using content "to text or data mine, or to develop or train any application, software, code, or data models, such as ChatGPT" ([Gale terms](https://www.cengagegroup.com/legal/terms-gale/)). Human reading only. |
| **Toyota TIS** | $580/yr, ~$20/48 h (forum, dated) ([TN forum](https://www.toyotanation.com/threads/techinfo-toyota-com-and-tis-technical-information-system.1671469/)) | OEM | Legal page unreachable (TLS error). |
| **Honda Service Express** | $20/3 d, $50/30 d, $500/yr; Honda and Acura separate (forum) ([Ridgeline](https://www.ridgelineownersclub.com/threads/price-increase-for-access-to-honda-service-information.222155/)) | OEM | Not read. |
| **Ford PTS / FDRS** | PTS ~$22/72 h; FDRS $120/2 d, $300/30 d, $1,200/yr (forum) ([Transit forum](https://www.fordtransitusaforum.com/threads/how-to-get-the-pdf-and-html-repair-manual-for-any-motorcraft-ford-vehicle-for-22.95911/)) | OEM | Not read. |
| **GM ACDelco TDS** | $20/3 d, $150/mo, $1,200/yr (~2017, dated) ([TechRoute66](https://techroute66.com/acdelco-tds)) | OEM | Not read. |
| **Stellantis techAUTHORITY** | $36.95/3 d, $1,978/yr ([wiTECH KB](https://kb.fcawitech.com/article/7th-how-to-purchase-a-techauthority-subscription-aftermarket-646.html), [Diagnoex](https://diagnoex.com/products/mopar-techauthority-subscription)) | OEM | Not read. |
| **Nissan / Hyundai / Kia** | Nissan $19.99/1 d, $75/mo, $720/yr ([Nissan TechInfo](https://www.nissan-techinfo.com/product.aspx?dept_id=18&sku=online1)); Hyundai $20/wk, $60/mo, $300/yr ([Hyundai PDF](https://www.hyundaitechinfo.com/external/files/HyundaiTechInfo_Service_Information_Subscriptions.pdf)); Kia $30/3 d, $150/mo, $1,500/yr ([Kia PDF](https://kiatechinfo.snapon.com/Forms/Subscription_Info.pdf)) | OEM | Not read. |

None of the vendor ToS I could read permit automated access, storage, or derivative works. The two I read with AI language (Gale) forbid it outright; ALLDATA and Mitchell are silent on AI but block the mechanisms.

**Recommended pattern for these:** Austin reads the vendor site himself, then writes his own words into a `curated` record with `source = "author's shop experience, cross-checked against ALLDATA"`. Facts (a torque spec, a test voltage) are not copyrightable in the US; the vendor's prose, tables and diagrams are. I found no verified case law on this; treat as a decision point (section 7).

## 6. AI/LLM automotive datasets, MCP servers, vendor APIs

- **MCP servers**: [ayhammouda/obd-mcp-server](https://glama.ai/mcp/servers/ayhammouda/obd-mcp-server), [farzadnadiri/MCP-CAN](https://github.com/farzadnadiri/mcp-can) (CAN, UDS, J1939 with simulator), [castlebbs/Vehicle-Diagnostic-Assistant](https://github.com/castlebbs/Vehicle-Diagnostic-Assistant), [joelcanepa/OBD2-mcp](https://glama.ai/mcp/servers/joelcanepa/OBD2-mcp), an Apify DTC + repair cost actor ([Apify](https://apify.com/dataengineered/obd2-dtc-code-repair-lookup/api/mcp)), and a DTC lookup connector that says its definitions are reworded from open/public sources ([Glama](https://glama.ai/mcp/connectors/com.mcpscores/vehicle-fault-codes/tools/dtc_lookup)). Nobody I found ships licensed repair playbooks. Data provenance in these is undocumented; treat as prior art, not a source.
- **CarAPI**: $199/$249/$299 per year (1,500/3,000/6,000 calls/day), 9,000+ OBD-II codes, VIN decode, caching explicitly encouraged; DTC source unnamed; no AI terms ([pricing](https://carapi.app/pricing)). A cheap way to get a cached, ToS-clean DTC lookup, but provenance is opaque, so tag provenance_unknown.
- **CarMD API**: paid, free tier 10 requests/day; diagnostics, repairs, recalls ([summary](https://dev.to/michaelakoster/free-alternatives-to-carmd-api-for-vehicle-data-a27), secondary). ToS not read.
- **VIN APIs**: DataOne is enterprise/quote, 50-decode trial; VinAudit NMVTIS ~$1 to $0.25/report; general market ~EUR 0.20-0.50 per decode ([Vincario comparison](https://vincario.com/blog/vin-decode-api-pricing/), a competitor's blog). Not needed given vPIC is free.
- **No commercial API found that licenses OEM/ALLDATA-class repair procedures for AI use.** Mitchell 1 lists a "web-intent & API request" support page ([page](https://mitchell1.com/support/web-intent/)), which I did not read; it appears to deep-link its own UI. Contacting Mitchell/ALLDATA for a written licence is the only compliant route to that content, and I would expect a commercial-scale price.

## 7. Recommendations

### Adopt first (ranked)
1. **NHTSA recalls + complaints + MfrComms (d).** Free, authoritative, per make/model/year, reaches back to 1995. Highest legit signal for "known issue on this vehicle".
2. **NHTSA vPIC (f).** Free VIN decode, offline DB available, covers 1980+.
3. **Hand-written PID/DTC tables from public facts + Wikipedia PIDs for reference (b, a).** Zero licensing exposure; matches design §8.
4. **Austin-reviewed playbooks (c).** The scarce and highest-value input; his shop experience becomes `curated` with `reviewed`.
5. **fueleconomy.gov (e).** Free specs for engine/cylinder/transmission context. (Runners-up: Wal33D DTC list as a `provenance_unknown` lookup for manufacturer-specific codes, OBDb for later Mode 22 on newer cars.)

### Avoid
1. **Operation CHARM.** Likely infringing content; ingesting it taints the store.
2. **Scraping AutoZone / RepairPal / CarComplaints / OBD-Codes.com.** Explicit robot/copying bans, low incremental value.
3. **Any paid vendor (ALLDATA, Mitchell, Gale/Chilton, OEM) used via automation, cache, or AI.** Gale bans it in writing; ALLDATA bans robots and storage.

### First ~50-record seed
- ~20 generic DTC records (P0171/P0174, P0300-P0308, P0420/P0430, P0440-series EVAP, P0442/P0455/P0456, P0113/P0117/P0128, P0335, P0101, P0507, U0100, charging/battery codes) hand-written with terse own-words meanings, checked against fabiovila and Wikipedia; tag `curated` if Austin reviews, else `model_drafted`.
- ~12 PID records (Mode 01 core: RPM, coolant temp, STFT/LTFT, MAF, MAP, O2 volts, load, timing, fuel pressure) from Wikipedia facts.
- ~10 playbooks (lean codes, misfire, P0420, charging, parasitic draw, no-start, overheating, EVAP, MAF, O2 sensor), `model_drafted` + `unreviewed` until Austin signs; cite only facts.
- ~8 test-value/spec notes marked `general_knowledge_unverified` unless Austin confirms.
- NHTSA data stays a runtime fetch, not seeded.

## 8. Legal posture (plain words, not legal advice)

- **Safe:** US government data (NHTSA, EPA/DOE); facts written in our own words; MIT/CC BY/CC BY-SA data used with the license's conditions (CC BY-SA needs attribution and share-alike on derivatives).
- **Risky:** MIT-labeled DTC lists with unknown upstream provenance. The repo license does not prove the uploader had the right to relicense.
- **Not safe:** copying vendor prose/tables/diagrams; automated access to sites whose ToS ban it; CHARM.
- **Gray, and Neil decides:** a human subscriber reading ALLDATA/library Chilton and then authoring original notes. Facts are generally free but I found no case law confirming; ToS may still bar use "in an AI product".
- **Records Neil needs to make:**
  1. Is `provenance_unknown` DTC data acceptable in a private tool, and is it excluded from any future distribution?
  2. Is Austin's "read pro source, write own words" workflow acceptable, and what does the `source` field say?
  3. Does the design ever add a credentialed connector? If so, each vendor's ToS needs a written decision (design §13.7); today none of the ToS I read would pass.
  4. Do we approach ALLDATA/Mitchell for a written licence? Opening a conversation is the only clean route.

## 9. Gaps and degradation

Unobtainable legitimately: OEM service procedures, factory test values per engine, wiring diagrams, manufacturer-specific DTC text with authority, and Mode 22 PIDs for pre-2008 cars (OBDb is modern-heavy; opendbc is 2016+).

Design should degrade like this:
- Missing record: answer with `[general knowledge, unverified]` and say "no reference record for this make/year".
- Manufacturer-specific code with no authoritative record: return the code, say it is manufacturer-specific, name the likely make family, and prompt the user to confirm from a manual.
- Test values: never give numbers unless a record carries them; otherwise say "check the factory spec" and log a `needs_reference` item for Austin.
- Show source and confidence on every claim (design §8 already); add a UI label for `provenance_unknown`.
- Log misses so Austin's review queue targets the most-asked gaps.

## 10. Could not verify

- License text of fabiovila/OBDIICodes and python-OBD (relied on design §8).
- NHTSA formal terms of use (403) and rate limits; whether the flat files carry any use restriction.
- Whether MfrComms rows include summary text beyond IDs/dates (design says summaries; I did not open the file).
- AutoZone repair guide provider/terms text (403); whether guides are ALLDATA-sourced.
- Operation CHARM: any takedown or lawsuit; the actual source of its content. HN comments are unverified opinion.
- ToS text for Identifix, Haynes, all OEM sites, CarAPI, CarMD, and any AI clause in ALLDATA/Mitchell (they are silent on AI; I found no explicit ban or grant).
- Current prices: OEM/forum figures are dated (GM ~2017); ProDemand DIY price not found; Haynes price is from a reseller article.
- Pre-2008 depth of NHTSA vPIC fields, OBD-Codes.com ToS, Wal33D dataset provenance and accuracy, contents of HF/Kaggle DTC sets.
- Whether any vendor would grant an AI-use license, and at what price.
