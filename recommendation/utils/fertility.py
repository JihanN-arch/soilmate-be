def calculate_fertility(soil):
    """Indeks kesuburan sederhana 0-1 dari pH, N, dan C-organik.

    `soil` berbentuk datar: {"ph": 5.6, "nitrogen": 1.2, "organic_carbon": 15.0}
    (nitrogen & C-organik dalam g/kg).
    """
    score = 0
    available = 0

    ph = soil.get("ph")
    if ph is not None:
        available += 1
        if 5.5 <= ph <= 7:
            score += 0.4
        elif 5 <= ph < 5.5:
            score += 0.3
        else:
            score += 0.1

    nitrogen = soil.get("nitrogen")
    if nitrogen is not None:
        available += 1
        if nitrogen > 2:
            score += 0.3
        elif nitrogen > 1:
            score += 0.2
        else:
            score += 0.1

    carbon = soil.get("organic_carbon")
    if carbon is not None:
        available += 1
        if carbon > 20:
            score += 0.3
        elif carbon > 10:
            score += 0.2
        else:
            score += 0.1

    if available == 0:
        return None
    return round(score, 2)
