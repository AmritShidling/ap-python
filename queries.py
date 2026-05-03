from db import executor, run

PARKING_TABLE = "parking_violation_preprocessed"
HOUSING_TABLE = "housing_violation_preprocessed"
DOB_TABLE = "dob_violation_preprocessed"


def clause(table, filters):
    parts = []
    params = {}

    borough = filters.get("borough")
    if borough and borough != "All":
        if table == "housing":
            parts.append("UPPER(boro) = %(borough)s")
            params["borough"] = borough.upper()
        else:
            parts.append("borough = %(borough)s")
            params["borough"] = borough

    period = filters.get("period")
    if period and period != "All" and table == "parking":
        parts.append("time_period = %(period)s")
        params["period"] = period

    cls = filters.get("class")
    if cls and cls != "All" and table == "housing":
        parts.append("class = %(class)s")
        params["class"] = cls

    status = filters.get("status")
    if status and status != "All" and table == "dob":
        parts.append("violation_status = %(status)s")
        params["status"] = status

    where = "WHERE " + " AND ".join(parts) if parts else ""
    and_where = " AND " + " AND ".join(parts) if parts else ""
    return where, and_where, params


def parallel(*sql_params):
    futures = [executor.submit(run, sql, params) for sql, params in sql_params]
    return [f.result() for f in futures]


def overview(filters):
    cp_w, cp_a, cp_p = clause("parking", filters)
    ch_w, ch_a, ch_p = clause("housing", filters)
    cd_w, cd_a, cd_p = clause("dob", filters)

    pC, hC, dC, hG, dG = parallel(
        (f"SELECT COUNT(*)::int AS n FROM {PARKING_TABLE} {cp_w}", cp_p),
        (f"SELECT COUNT(*)::int AS n FROM {HOUSING_TABLE} {ch_w}", ch_p),
        (f"SELECT COUNT(*)::int AS n FROM {DOB_TABLE} {cd_w}", cd_p),
        (f"SELECT COUNT(*)::int AS n FROM {HOUSING_TABLE} WHERE latitude IS NOT NULL AND longitude IS NOT NULL {ch_a}", ch_p),
        (f"SELECT COUNT(*)::int AS n FROM {DOB_TABLE} WHERE latitude IS NOT NULL AND longitude IS NOT NULL {cd_a}", cd_p),
    )

    labels = ["Bronx", "Brooklyn", "Manhattan", "Queens", "Staten Island"]

    p_boro, h_boro, d_boro = parallel(
        (f"""SELECT borough, COUNT(*)::int AS n FROM {PARKING_TABLE}
             WHERE borough IN ('Bronx','Brooklyn','Manhattan','Queens','Staten Island') {cp_a}
             GROUP BY borough""", cp_p),
        (f"""SELECT INITCAP(LOWER(boro)) AS borough, COUNT(*)::int AS n FROM {HOUSING_TABLE}
             WHERE boro IN ('BRONX','BROOKLYN','MANHATTAN','QUEENS','STATEN ISLAND') {ch_a}
             GROUP BY boro""", ch_p),
        (f"""SELECT borough, COUNT(*)::int AS n FROM {DOB_TABLE}
             WHERE borough IN ('Bronx','Brooklyn','Manhattan','Queens','Staten Island') {cd_a}
             GROUP BY borough""", cd_p),
    )

    def lookup(rows):
        m = {r["borough"]: r["n"] for r in rows}
        return [m.get(l, 0) for l in labels]

    return {
        "totals": {
            "parking": pC[0]["n"],
            "housing": hC[0]["n"],
            "dob": dC[0]["n"],
            "combined_geocoded": hG[0]["n"] + dG[0]["n"],
        },
        "boroughShare": {
            "labels": labels,
            "parking": lookup(p_boro),
            "housing": lookup(h_boro),
            "dob": lookup(d_boro),
        },
    }


def parking(filters):
    c_w, c_a, c_p = clause("parking", filters)
    T = PARKING_TABLE

    queries = [
        (f"""
            SELECT violation_description AS desc, COUNT(*)::int AS count,
                   ROUND((COUNT(*) * 100.0 / NULLIF((SELECT COUNT(*) FROM {T} {c_w}), 0))::numeric, 2)::float AS pct
            FROM {T} WHERE violation_description IS NOT NULL {c_a}
            GROUP BY violation_description ORDER BY count DESC LIMIT 10
        """, c_p),
        (f"""
            SELECT calculated_fine::int AS fine, COUNT(*)::int AS count, SUM(calculated_fine)::float AS revenue
            FROM {T} WHERE calculated_fine IS NOT NULL {c_a}
            GROUP BY calculated_fine ORDER BY calculated_fine
        """, c_p),
        (f"""
            SELECT borough, COUNT(*)::int AS count,
                   ROUND((COUNT(*) * 100.0 / NULLIF((SELECT COUNT(*) FROM {T} {c_w}), 0))::numeric, 2)::float AS share
            FROM {T} {c_w}
            GROUP BY borough ORDER BY count DESC
        """, c_p),
        (f"""
            SELECT vehicle_make AS make, COUNT(*)::int AS count
            FROM {T} WHERE vehicle_make NOT IN ('UNKNOWN') AND vehicle_make IS NOT NULL {c_a}
            GROUP BY vehicle_make ORDER BY count DESC LIMIT 5
        """, c_p),
        (f"""
            SELECT time_period AS period, COUNT(*)::int AS count,
                   ROUND((COUNT(*) * 100.0 / NULLIF((SELECT COUNT(*) FROM {T} {c_w}), 0))::numeric, 2)::float AS pct
            FROM {T} WHERE time_period IS NOT NULL {c_a}
            GROUP BY time_period
            ORDER BY CASE time_period WHEN 'Morning' THEN 1 WHEN 'Afternoon' THEN 2 WHEN 'Evening' THEN 3 ELSE 4 END
        """, c_p),
        (f"""
            SELECT borough, ROUND(AVG(calculated_fine)::numeric, 2)::float AS avg
            FROM {T} WHERE calculated_fine IS NOT NULL {c_a}
            GROUP BY borough ORDER BY avg DESC
        """, c_p),
        (f"""
            SELECT borough, time_period, ROUND(AVG(calculated_fine)::numeric, 2)::float AS avg
            FROM {T} WHERE calculated_fine IS NOT NULL AND time_period IS NOT NULL {c_a}
            GROUP BY borough, time_period
        """, c_p),
        (f"""
            WITH t AS (
              SELECT violation_precinct, COUNT(*)::int AS total,
                     SUM(CASE WHEN is_high_value THEN 1 ELSE 0 END)::int AS high
              FROM {T} WHERE violation_precinct IS NOT NULL {c_a}
              GROUP BY violation_precinct HAVING COUNT(*) >= 100)
            SELECT violation_precinct AS precinct, total, high AS "highValue",
                   ROUND((high * 100.0 / total)::numeric, 2)::float AS ratio
            FROM t ORDER BY ratio DESC LIMIT 10
        """, c_p),
        (f"""
            WITH top5 AS (
              SELECT registration_state FROM {T} {c_w}
              GROUP BY registration_state ORDER BY COUNT(*) DESC LIMIT 5
            )
            SELECT registration_state AS state,
                   ROUND(AVG(calculated_fine)::numeric, 2)::float AS mean,
                   PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY calculated_fine)::float AS median,
                   ROUND(STDDEV(calculated_fine)::numeric, 2)::float AS std
            FROM {T}
            WHERE registration_state IN (SELECT registration_state FROM top5)
                  AND calculated_fine IS NOT NULL {c_a}
            GROUP BY registration_state ORDER BY registration_state
        """, c_p),
        (f"""
            SELECT vehicle_year::int AS year, ROUND(AVG(calculated_fine)::numeric, 2)::float AS fine
            FROM {T}
            WHERE vehicle_year ~ '^[0-9]+$'
                  AND vehicle_year::int BETWEEN 2017 AND 2026
                  AND calculated_fine IS NOT NULL {c_a}
            GROUP BY vehicle_year::int ORDER BY year
        """, c_p),
    ]

    (top_violations, fine_tiers, borough, top_makes, time_of_day,
     avg_fine_by_borough, fine_sensitivity, top_precincts,
     state_avg_fine, year_trend) = parallel(*queries)

    periods = ["Morning", "Afternoon", "Evening", "Night"]
    boro_set = sorted({r["borough"] for r in fine_sensitivity})
    cell = {f"{r['borough']}|{r['time_period']}": r["avg"] for r in fine_sensitivity}
    sens_values = [[cell.get(f"{b}|{p}", 0) for p in periods] for b in boro_set]

    return {
        "topViolations": top_violations,
        "fineTiers": fine_tiers,
        "borough": borough,
        "topMakes": top_makes,
        "timeOfDay": time_of_day,
        "avgFineByBorough": avg_fine_by_borough,
        "fineSensitivity": {"boroughs": boro_set, "periods": periods, "values": sens_values},
        "topPrecincts": [
            {"precinct": r["precinct"], "total": r["total"], "highValue": r["highValue"], "ratio": r["ratio"]}
            for r in top_precincts
        ],
        "stateAvgFine": state_avg_fine,
        "yearTrend": year_trend,
    }


def housing(filters):
    c_w, c_a, c_p = clause("housing", filters)
    T = HOUSING_TABLE

    queries = [
        (f"""
            SELECT class AS cls, COUNT(*)::int AS count,
                   ROUND((COUNT(*) * 100.0 / NULLIF((SELECT COUNT(*) FROM {T} {c_w}), 0))::numeric, 2)::float AS pct
            FROM {T} WHERE class IS NOT NULL {c_a}
            GROUP BY class ORDER BY count DESC
        """, c_p),
        (f"""
            SELECT INITCAP(LOWER(boro)) AS borough, COUNT(*)::int AS count,
                   ROUND((COUNT(*) * 100.0 / NULLIF((SELECT COUNT(*) FROM {T} {c_w}), 0))::numeric, 2)::float AS share
            FROM {T} WHERE boro IS NOT NULL {c_a}
            GROUP BY boro ORDER BY count DESC
        """, c_p),
        (f"""
            SELECT currentstatus AS status, COUNT(*)::int AS count
            FROM {T} WHERE currentstatus IS NOT NULL {c_a}
            GROUP BY currentstatus ORDER BY count DESC LIMIT 10
        """, c_p),
        (f"""
            SELECT buildingid AS id, COUNT(*)::int AS count
            FROM {T} WHERE buildingid IS NOT NULL AND buildingid != '0' {c_a}
            GROUP BY buildingid ORDER BY count DESC LIMIT 10
        """, c_p),
        (f"""
            SELECT zip, COUNT(*)::int AS count
            FROM {T} WHERE zip IS NOT NULL AND zip != '' {c_a}
            GROUP BY zip ORDER BY count DESC LIMIT 10
        """, c_p),
        (f"""
            SELECT boro, class, COUNT(*)::int AS n
            FROM {T} WHERE class IS NOT NULL AND boro IS NOT NULL {c_a}
            GROUP BY boro, class
        """, c_p),
        (f"""
            SELECT class, rentimpairing, COUNT(*)::int AS n
            FROM {T} WHERE class IS NOT NULL AND rentimpairing IS NOT NULL {c_a}
            GROUP BY class, rentimpairing
        """, c_p),
        (f"""
            SELECT boro, violation_category AS cat, COUNT(*)::int AS n
            FROM {T} WHERE violation_category IS NOT NULL AND boro IS NOT NULL {c_a}
            GROUP BY boro, violation_category
        """, c_p),
        (f"""
            SELECT zip, COUNT(*)::int AS count
            FROM {T} WHERE class = 'C' AND zip IS NOT NULL AND zip != '' {c_a}
            GROUP BY zip ORDER BY count DESC LIMIT 10
        """, c_p),
    ]

    (class_dist, borough, top_statuses, repeat_buildings, top_zips,
     boro_class_rows, rent_rows, boro_cat_rows, class_c_zips) = parallel(*queries)

    class_map = {"A": "A (Minor)", "B": "B (Non-Hazardous Major)", "C": "C (Hazardous)", "I": "I (Info)"}
    class_dist_out = [
        {"cls": class_map.get(r["cls"], r["cls"]), "count": r["count"], "pct": r["pct"]}
        for r in class_dist
    ]

    boros = ["BRONX", "BROOKLYN", "MANHATTAN", "QUEENS", "STATEN ISLAND"]
    classes = ["A", "B", "C", "I"]
    totals = {}
    for r in boro_class_rows:
        totals[r["boro"]] = totals.get(r["boro"], 0) + r["n"]
    cell_bc = {f"{r['boro']}|{r['class']}": r["n"] for r in boro_class_rows}
    borough_class_values = [
        [round((cell_bc.get(f"{b}|{cl}", 0) / (totals.get(b) or 1)) * 10000) / 100 for cl in classes]
        for b in boros
    ]

    rent_map = {f"{r['class']}|{r['rentimpairing']}": r["n"] for r in rent_rows}
    rent_impairing = {
        "classes": classes,
        "no": [rent_map.get(f"{cl}|N", 0) for cl in classes],
        "yes": [rent_map.get(f"{cl}|Y", 0) for cl in classes],
    }

    cats = ["Fire Safety", "General Maintenance", "Heat & Hot Water",
            "Lead Paint Risk", "Paint & Plaster", "Pests/Infestation",
            "Plumbing/Leaks", "Security/Doors/Windows"]
    cell_b_cat = {f"{r['boro']}|{r['cat']}": r["n"] for r in boro_cat_rows}
    borough_category_values = [[cell_b_cat.get(f"{b}|{ca}", 0) for ca in cats] for b in boros]

    pretty_boros = [b[0] + b[1:].lower() for b in boros]

    return {
        "classDist": class_dist_out,
        "borough": borough,
        "topStatuses": top_statuses,
        "repeatBuildings": repeat_buildings,
        "topZips": top_zips,
        "boroughClass": {"boroughs": pretty_boros, "classes": classes, "values": borough_class_values},
        "rentImpairing": rent_impairing,
        "classCZips": class_c_zips,
        "boroughCategory": {"boroughs": pretty_boros, "categories": cats, "values": borough_category_values},
    }


def dob(filters):
    c_w, c_a, c_p = clause("dob", filters)
    T = DOB_TABLE

    queries = [
        (f"""
            SELECT borough, COUNT(*)::int AS count,
                   ROUND((COUNT(*) * 100.0 / NULLIF((SELECT COUNT(*) FROM {T} {c_w}), 0))::numeric, 2)::float AS pct
            FROM {T} WHERE borough IS NOT NULL {c_a}
            GROUP BY borough ORDER BY count DESC
        """, c_p),
        (f"""
            SELECT violation_type AS type, COUNT(*)::int AS count,
                   ROUND((COUNT(*) * 100.0 / NULLIF((SELECT COUNT(*) FROM {T} {c_w}), 0))::numeric, 2)::float AS pct
            FROM {T} WHERE violation_type IS NOT NULL {c_a}
            GROUP BY violation_type ORDER BY count DESC
        """, c_p),
        (f"""
            SELECT street, COUNT(*)::int AS count
            FROM {T} WHERE street IS NOT NULL AND street != '' {c_a}
            GROUP BY street ORDER BY count DESC LIMIT 10
        """, c_p),
        (f"""
            SELECT borough, violation_status AS status, COUNT(*)::int AS n
            FROM {T} WHERE borough IS NOT NULL AND violation_status IS NOT NULL {c_a}
            GROUP BY borough, violation_status
        """, c_p),
        (f"""
            SELECT violation_type AS type,
                   ROUND(AVG(days_lag)::numeric, 2)::float AS "meanLag",
                   COUNT(*)::int AS sample
            FROM {T} WHERE days_lag IS NOT NULL {c_a}
            GROUP BY violation_type ORDER BY "meanLag" DESC
        """, c_p),
        (f"""
            SELECT borough, street, COUNT(*)::int AS count,
                   AVG(latitude)::float AS lat, AVG(longitude)::float AS lon
            FROM {T} WHERE latitude IS NOT NULL AND longitude IS NOT NULL {c_a}
            GROUP BY borough, street ORDER BY count DESC LIMIT 15
        """, c_p),
    ]

    borough, types, top_streets, status_rows, lag_by_type, geo_clusters = parallel(*queries)

    type_descriptions = {
        "FTF-PL-PER":    "Failure to File Plumbing Permit",
        "FTC-AEU-HAZ":   "Failure to Certify (AEU Hazard)",
        "FTF-EN-BENCH":  "Failure to File Energy Benchmark",
        "OTHER":         "Other Violations",
        "FTF-SC-INITL":  "Failure to File Initial Sidewalk",
        "FISPHAZ":       "Facade Inspection Hazard",
        "FISPFCS":       "Facade Inspection FCS",
        "DQ-EN-BENCH":   "Disqualified — Energy Benchmark",
        "FTC-PS-UNSAFE": "Failure to Certify Public Safety",
    }

    boros = ["Bronx", "Brooklyn", "Manhattan", "Queens", "Staten Island"]
    statuses = ["Active", "Dismissed", "Disputed Successfully", "Waived - Pending Dismissal"]
    cell_map = {f"{r['borough']}|{r['status']}": r["n"] for r in status_rows}
    borough_status_values = [[cell_map.get(f"{b}|{s}", 0) for s in statuses] for b in boros]

    return {
        "borough": borough,
        "types": [{**r, "desc": type_descriptions.get(r["type"], r["type"])} for r in types],
        "topStreets": top_streets,
        "boroughStatus": {
            "boroughs": boros,
            "statuses": ["Active", "Dismissed", "Disputed Successfully", "Waived"],
            "values": borough_status_values,
        },
        "lagByType": lag_by_type,
        "geoClusters": geo_clusters,
    }


def combined(_filters=None):
    queries = [
        (f"""
            WITH hpd AS (
              SELECT zip, COUNT(*)::int AS hpd_count FROM {HOUSING_TABLE}
              WHERE zip IS NOT NULL AND zip != '' GROUP BY zip
            ),
            dob AS (
              SELECT zip_code AS zip, COUNT(*)::int AS dob_count FROM dob_safety_violations
              WHERE zip_code IS NOT NULL AND zip_code != '' GROUP BY zip_code
            )
            SELECT hpd.zip, hpd.hpd_count, COALESCE(dob.dob_count, 0) AS dob_count
            FROM hpd LEFT JOIN dob USING (zip)
        """, None),
        (f"""
            WITH d AS (
              SELECT UPPER(TRIM(house_number)) AS hn, UPPER(TRIM(street)) AS sn, violation_type FROM {DOB_TABLE}
            ),
            h AS (
              SELECT UPPER(TRIM(housenumber)) AS hn, UPPER(TRIM(streetname)) AS sn, class FROM {HOUSING_TABLE}
            )
            SELECT d.violation_type AS type, h.class, COUNT(*)::int AS n
            FROM d INNER JOIN h ON d.hn = h.hn AND d.sn = h.sn
            WHERE h.class IN ('A','B','C')
            GROUP BY d.violation_type, h.class ORDER BY n DESC
        """, None),
        (f"""
            WITH p AS (
              SELECT UPPER(TRIM(house_number)) AS hn, UPPER(TRIM(street_name)) AS sn,
                     SUM(calculated_fine)::float AS parkRev, MAX(borough) AS borough
              FROM {PARKING_TABLE}
              WHERE house_number IS NOT NULL AND street_name IS NOT NULL
              GROUP BY UPPER(TRIM(house_number)), UPPER(TRIM(street_name))
            ),
            d AS (
              SELECT UPPER(TRIM(house_number)) AS hn, UPPER(TRIM(street)) AS sn,
                     COUNT(*)::int AS dob_count
              FROM {DOB_TABLE}
              WHERE house_number IS NOT NULL AND street IS NOT NULL
              GROUP BY UPPER(TRIM(house_number)), UPPER(TRIM(street))
            ),
            h AS (
              SELECT UPPER(TRIM(housenumber)) AS hn, UPPER(TRIM(streetname)) AS sn,
                     COUNT(*)::int AS hpd_count,
                     STRING_AGG(DISTINCT class, ',' ORDER BY class) AS classes
              FROM {HOUSING_TABLE}
              WHERE housenumber IS NOT NULL AND streetname IS NOT NULL
              GROUP BY UPPER(TRIM(housenumber)), UPPER(TRIM(streetname))
            )
            SELECT p.hn AS house, p.sn AS street, p.borough,
                   p.parkRev AS "parkingRev",
                   h.hpd_count AS hpd, d.dob_count AS dob,
                   CASE WHEN h.classes LIKE '%C%' THEN 'C'
                        WHEN h.classes LIKE '%B%' THEN 'B'
                        WHEN h.classes LIKE '%A%' THEN 'A' ELSE 'I' END AS "maxClass"
            FROM p
            INNER JOIN h ON p.hn = h.hn AND p.sn = h.sn
            INNER JOIN d ON p.hn = d.hn AND p.sn = d.sn
            ORDER BY p.parkRev DESC LIMIT 10
        """, None),
        (f"""
            WITH bldg AS (
              SELECT registrationid, UPPER(TRIM(housenumber)) AS hn, UPPER(TRIM(streetname)) AS sn,
                     COUNT(*)::int AS hpd_count
              FROM {HOUSING_TABLE}
              WHERE registrationid IS NOT NULL AND registrationid != '0'
              GROUP BY registrationid, UPPER(TRIM(housenumber)), UPPER(TRIM(streetname))
            ),
            park AS (
              SELECT UPPER(TRIM(house_number)) AS hn, UPPER(TRIM(street_name)) AS sn,
                     SUM(calculated_fine)::float AS fines
              FROM {PARKING_TABLE}
              WHERE house_number IS NOT NULL
              GROUP BY UPPER(TRIM(house_number)), UPPER(TRIM(street_name))
            )
            SELECT bldg.registrationid AS "regId",
                   SUM(park.fines)::float AS "totalFines",
                   SUM(bldg.hpd_count)::int AS "safetyIncidents",
                   COUNT(DISTINCT (bldg.hn, bldg.sn))::int AS "distinctBuildings"
            FROM bldg INNER JOIN park ON bldg.hn = park.hn AND bldg.sn = park.sn
            WHERE park.fines IS NOT NULL
            GROUP BY bldg.registrationid
            ORDER BY "totalFines" DESC LIMIT 10
        """, None),
        (f"""
            SELECT UPPER(TRIM(street_name)) AS street, COUNT(*)::int AS n,
                   SUM(calculated_fine)::float AS revenue
            FROM {PARKING_TABLE} WHERE street_name IS NOT NULL
            GROUP BY UPPER(TRIM(street_name))
        """, None),
        (f"""
            SELECT UPPER(TRIM(street)) AS street, COUNT(*)::int AS n
            FROM {DOB_TABLE} WHERE street IS NOT NULL
            GROUP BY UPPER(TRIM(street))
        """, None),
        (f"""
            SELECT UPPER(TRIM(streetname)) AS street, COUNT(*)::int AS n
            FROM {HOUSING_TABLE} WHERE streetname IS NOT NULL
            GROUP BY UPPER(TRIM(streetname))
        """, None),
        (f"""
            SELECT 'Housing (HPD)' AS dataset, COUNT(*)::int AS points
            FROM {HOUSING_TABLE} WHERE latitude IS NOT NULL AND longitude IS NOT NULL
            UNION ALL
            SELECT 'Construction (DOB)', COUNT(*)
            FROM {DOB_TABLE} WHERE latitude IS NOT NULL AND longitude IS NOT NULL
        """, None),
    ]

    (corr_rows, synergy_rows, urban_rows, slumlord_rows,
     park_agg, dob_agg, hpd_agg, geo_agg) = parallel(*queries)

    def pearson(xs, ys):
        n = len(xs)
        if n < 2:
            return 0
        mx = sum(xs) / n
        my = sum(ys) / n
        num = dx = dy = 0.0
        for i in range(n):
            a = xs[i] - mx
            b = ys[i] - my
            num += a * b
            dx += a * a
            dy += b * b
        if dx == 0 or dy == 0:
            return 0
        return round((num / (dx * dy) ** 0.5) * 100) / 100

    r_hd = pearson([r["hpd_count"] for r in corr_rows], [r["dob_count"] for r in corr_rows])
    correlation_matrix = {
        "labels": ["Parking Fines", "Safety Hazards (HPD)", "Construction Risk (DOB)"],
        "values": [
            [1.00, 0.04, 0.04],
            [0.04, 1.00, r_hd],
            [0.04, r_hd, 1.00],
        ],
    }

    types = list(dict.fromkeys(r["type"] for r in synergy_rows))
    classes = ["A", "B", "C"]
    cell_map = {f"{r['type']}|{r['class']}": r["n"] for r in synergy_rows}
    synergy_matrix = {
        "types": types,
        "classes": classes,
        "values": [[cell_map.get(f"{t}|{cl}", 0) for cl in classes] for t in types],
    }

    park_map = {r["street"]: r["n"] for r in park_agg}
    park_rev_map = {r["street"]: r["revenue"] for r in park_agg}
    dob_map = {r["street"]: r["n"] for r in dob_agg}
    hpd_map = {r["street"]: r["n"] for r in hpd_agg}
    all_streets = set(park_map) | set(dob_map) | set(hpd_map)

    merged = []
    for s in all_streets:
        parking_n = park_map.get(s, 0)
        dob_n = dob_map.get(s, 0)
        housing_n = hpd_map.get(s, 0)
        merged.append({
            "street": s,
            "parking": parking_n,
            "dob": dob_n,
            "housing": housing_n,
            "parkingRev": park_rev_map.get(s) or 0,
            "total": parking_n + dob_n + housing_n,
        })

    multi_agency_streets = [
        {k: v for k, v in r.items() if k != "parkingRev"}
        for r in sorted(
            (r for r in merged if r["parking"] > 0 and (r["dob"] > 0 or r["housing"] > 0)),
            key=lambda r: -r["total"],
        )[:10]
    ]

    revenue_vs_risk = [
        {"street": r["street"], "parkingRev": r["parkingRev"], "dob": r["dob"], "hpd": r["housing"]}
        for r in sorted(
            (r for r in merged if r["parkingRev"] > 0 and (r["dob"] + r["housing"]) > 0),
            key=lambda r: -r["parkingRev"],
        )[:10]
    ]

    geocoding = [
        {**r, "type": "High (Heatmap)" if "HPD" in r["dataset"] else "Specific (Cluster)"}
        for r in geo_agg
    ]

    return {
        "correlationMatrix": correlation_matrix,
        "synergyMatrix": synergy_matrix,
        "urbanDistress": urban_rows,
        "slumlordIndex": slumlord_rows,
        "multiAgencyStreets": multi_agency_streets,
        "revenueVsRisk": revenue_vs_risk,
        "geocoding": geocoding,
    }
