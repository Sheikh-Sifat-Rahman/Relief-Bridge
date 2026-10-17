def calculate_priority_score(aid_request):
    score = {"DESTROYED": 30, "SEVERE": 20, "PARTIAL": 10}.get(
        aid_request.house_damage, 0
    )
    score += 20 * aid_request.income_lost + 15 * aid_request.displaced
    score += 15 * (not aid_request.safe_water_available)
    score += min(aid_request.children_count * 3, 15) + min(
        aid_request.elderly_count * 5, 15
    )
    score = min(score, 100)
    return (
        score,
        "CRITICAL"
        if score >= 70
        else "HIGH"
        if score >= 50
        else "MEDIUM"
        if score >= 30
        else "LOW",
    )
