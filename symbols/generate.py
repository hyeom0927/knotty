# -*- coding: utf-8 -*-
"""Knotty 도안 기호 아이콘 생성기

모든 아이콘의 좌표를 이 파일 한 곳에서 관리합니다.
새 기법을 추가할 때는 ICONS에 항목을 추가하고 이 스크립트를 다시 실행하세요.

    python3 symbols/generate.py

그리기 규칙은 docs/SYMBOLS.md 를 참고하세요.
"""
import os

# ── 공통 규격 ────────────────────────────────────────────────
#   캔버스   24 × 24
#   안전영역 2px (좌표는 2~22 안에)
#   선 굵기  2 (예외 없음)
#   색       currentColor — 글자색을 그대로 따라가므로 다크모드에서도 보입니다
TEMPLATE = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" '
    'width="24" height="24" fill="none" stroke="currentColor" '
    'stroke-width="2" stroke-linecap="round" stroke-linejoin="round" '
    'role="img" aria-label="{label}">\n  <title>{label}</title>\n{body}\n</svg>\n'
)

L = lambda d: f'  <path d="{d}"/>'
DOT = lambda cx, cy, r=2.2: f'  <circle cx="{cx}" cy="{cy}" r="{r}" fill="currentColor" stroke="none"/>'

# 긴뜨기 계열 공통 골격: 윗바 + 세로 기둥. 빗금 개수로 높이를 구분합니다.
T_BAR, T_STEM = "M5 3h14", "M12 3v18"

ICONS = {
    # ── 코바늘: 기본 ────────────────────────────────────────
    "ch":     ("사슬뜨기",   ['  <ellipse cx="12" cy="12" rx="9" ry="5"/>']),
    "sl_st":  ("빼뜨기",     [DOT(12, 12, 4.5)]),
    "sc":     ("짧은뜨기",   [L("M6 6 18 18"), L("M18 6 6 18")]),
    "hdc":    ("긴뜨기",     [L(T_BAR), L(T_STEM)]),
    "dc":     ("한길긴뜨기", [L(T_BAR), L(T_STEM), L("M8 14l8-4")]),
    "tr":     ("두길긴뜨기", [L(T_BAR), L(T_STEM), L("M8 11l8-4"), L("M8 17l8-4")]),
    "dtr":    ("세길긴뜨기", [L(T_BAR), L(T_STEM), L("M8 9l8-4"), L("M8 14l8-4"), L("M8 19l8-4")]),
    "mr":     ("매직링",     ['  <circle cx="12" cy="10" r="7"/>', L("M12 17v4")]),

    # ── 코바늘: 늘림(V) · 줄임(Λ) ────────────────────────────
    #    한길긴뜨기 계열은 위에 가로 막대를 붙여 짧은뜨기 계열과 구분합니다.
    "inc":    ("짧은뜨기 2코 늘려뜨기",   [L("M5 4 12 20 19 4")]),
    "dec":    ("짧은뜨기 2코 모아뜨기",   [L("M5 20 12 4 19 20")]),
    "sc3tog": ("짧은뜨기 3코 모아뜨기",   [L("M4 20 12 4 20 20"), L("M12 4v16")]),
    #    늘림 계열: 다리 개수 = 한 코에 뜨는 개수, 윗바 = 기둥이 있는 기법,
    #               빗금 개수 = 기둥 높이 (기본 기법과 같은 규칙)
    "hdc2inc": ("긴뜨기 2코 늘려뜨기",     [L("M7 5 12 20 17 5"), L("M4 5h6"), L("M14 5h6")]),
    "dc2inc": ("한길긴뜨기 2코 늘려뜨기", [L("M7 5 12 20 17 5"), L("M4 5h6"), L("M14 5h6"),
                                          L("M8 13l8-3")]),
    "sc3inc": ("짧은뜨기 3코 늘려뜨기",   [L("M4 5 12 20 20 5"), L("M12 5v15")]),
    "tr3inc": ("두길긴뜨기 3코 늘려뜨기", [L("M4 5 12 20 20 5"), L("M12 5v15"), L("M3 5h18"),
                                          L("M8 12l8-3"), L("M8 17l8-3")]),
    "dc2tog": ("한길긴뜨기 2코 모아뜨기", [L("M6 20 12 7 18 20"), L("M12 7V4"), L("M6 4h12")]),
    "dc3tog": ("한길긴뜨기 3코 모아뜨기", [L("M4 20 12 7 20 20"), L("M12 20V4"), L("M4 4h16")]),
    "dc4tog": ("한길긴뜨기 4코 모아뜨기", [L("M3 20 12 7 21 20"), L("M12 7 8 20"), L("M12 7 16 20"),
                                          L("M12 7V4"), L("M3 4h18")]),

    # ── 코바늘: 입체 무늬 ───────────────────────────────────
    #    셋 다 한 코에 여러 번 떠서 부풀리는 기법이라 형태가 비슷합니다.
    #    퍼프=속이 보이는 다발 / 구슬=다발+윗바 / 팝콘=닫힌 주머니+윗바
    "puff":    ("긴뜨기 5코 퍼프뜨기",
                [L("M12 4c-5 3-5 13 0 16"), L("M12 4c5 3 5 13 0 16"), L("M12 4v16")]),
    "bobble":  ("한길긴뜨기 5코 구슬뜨기",
                [L("M6 4h12"), L("M12 4c-5 3-5 13 0 16"), L("M12 4c5 3 5 13 0 16"), L("M12 4v16")]),
    "popcorn": ("한길긴뜨기 5코 팝콘뜨기",
                [L("M6 4h12"), L("M12 4c-6 3-6 13 0 16 6-3 6-13 0-16Z")]),

    # ── 코바늘: 걸어뜨기 (기둥 아래가 앞/뒤로 휩니다) ─────────
    "fpdc": ("앞걸어 한길긴뜨기", [L(T_BAR), L("M12 3v11c0 4 3 6 6 5"), L("M8 12l8-4")]),
    "bpdc": ("뒤걸어 한길긴뜨기", [L(T_BAR), L("M12 3v11c0 4-3 6-6 5"), L("M8 12l8-4")]),

    # ── 코바늘: 뜨는 위치 (두 반코 중 어디에 바늘을 넣는가) ────
    "flo":  ("앞이랑뜨기", [L("M4 9h16"), L("M4 16h16"), DOT(12, 9)]),
    "blo":  ("뒤이랑뜨기", [L("M4 9h16"), L("M4 16h16"), DOT(12, 16)]),

    # ── 코바늘: 마무리 ──────────────────────────────────────
    "crab": ("새우뜨기", [L("M19 5H6"), L("M9 2 6 5l3 3"), L("M8 11 16 19"), L("M16 11 8 19")]),

    # ── 대바늘 ─────────────────────────────────────────────
    "k":     ("겉뜨기",                 [L("M12 3v18")]),
    "p":     ("안뜨기",                 [L("M3 12h18")]),
    "yo":    ("바늘비우기",             ['  <circle cx="12" cy="12" r="6"/>']),
    "k2tog": ("겉뜨기 2코 모아뜨기",    [L("M6 19 18 5")]),
    "ssk":   ("왼코 겹쳐 2코 모아뜨기", [L("M18 19 6 5")]),
    "co":    ("코잡기", [L("M3 18h18"), L("M5 18a3.5 3.5 0 0 1 7 0"), L("M12 18a3.5 3.5 0 0 1 7 0")]),
}


def main():
    out = os.path.dirname(os.path.abspath(__file__))

    for code, (label, body) in ICONS.items():
        svg = TEMPLATE.format(label=label, body="\n".join(body))
        with open(os.path.join(out, f"{code}.svg"), "w", encoding="utf-8") as f:
            f.write(svg)

    # 검수용 대지 — 브라우저로 열어 한눈에 확인합니다
    cols, cell, pad = 7, 96, 12
    rows = (len(ICONS) + cols - 1) // cols
    width, height = cols * cell, rows * cell
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}">',
        f'<rect width="{width}" height="{height}" fill="#ffffff"/>',
    ]
    for i, (code, (label, body)) in enumerate(ICONS.items()):
        cx, cy = (i % cols) * cell, (i // cols) * cell
        parts.append(f'<rect x="{cx+4}" y="{cy+4}" width="{cell-8}" height="{cell-8}" '
                     f'fill="none" stroke="#e2e8f0"/>')
        parts.append(f'<g transform="translate({cx+pad+14},{cy+pad}) scale(2)" fill="none" '
                     f'stroke="#0f172a" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">')
        parts.append("\n".join(body).replace("currentColor", "#0f172a"))
        parts.append("</g>")
        parts.append(f'<text x="{cx+cell/2}" y="{cy+cell-12}" font-family="Helvetica" '
                     f'font-size="11" fill="#334155" text-anchor="middle">{code}</text>')
    parts.append("</svg>")

    with open(os.path.join(out, "preview.svg"), "w", encoding="utf-8") as f:
        f.write("\n".join(parts))

    print(f"✅ 아이콘 {len(ICONS)}개 + preview.svg 생성 완료 → {out}")


if __name__ == "__main__":
    main()
