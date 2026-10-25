"""生成随应用附带的英文演示 PDF（两页，A4）。

这是开发者脚本，运行一次即可重新生成 resources/demo/sample.pdf。
"""

from __future__ import annotations

import os

import fitz

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "resources", "demo", "sample.pdf")

NAVY = (0.075, 0.145, 0.196)
INK = (0.12, 0.16, 0.18)
MUTED = (0.36, 0.41, 0.42)
ACCENT = (0.78, 0.34, 0.20)
RULE = (0.82, 0.84, 0.81)
PAPER = (1, 1, 1)
SOFT = (0.965, 0.953, 0.932)


def put(page, rect, text, size=9.5, font="helv", color=INK, align=0, lineheight=1.32,
        label=""):
    result = page.insert_textbox(
        fitz.Rect(rect), text, fontsize=size, fontname=font, color=color,
        align=align, lineheight=lineheight,
    )
    if result < 0:
        print(f"  ! overflow {label or text[:28]!r}: {result:.1f}")
    return result


def page_frame(page, number, section):
    width, height = page.rect.width, page.rect.height
    page.draw_rect(fitz.Rect(0, 0, width, height), color=None, fill=PAPER)
    page.draw_rect(fitz.Rect(0, 0, 34, height), color=None, fill=NAVY)
    page.draw_rect(fitz.Rect(34, 0, 39, height), color=None, fill=ACCENT)
    page.draw_line(fitz.Point(68, 64), fitz.Point(width - 68, 64),
                   color=RULE, width=0.7)
    page.insert_text((68, 49), "URBAN SYSTEMS LAB", fontsize=7.5,
                     fontname="hebo", color=NAVY)
    page.insert_text((width - 68 - 54, 49), section, fontsize=7.5,
                     fontname="hebo", color=ACCENT)
    page.draw_line(fitz.Point(68, height - 48), fitz.Point(width - 68, height - 48),
                   color=RULE, width=0.7)
    page.insert_text((68, height - 30), "FIELD NOTE 07  /  2025", fontsize=7,
                     fontname="helv", color=MUTED)
    page.insert_text((width - 82, height - 30), number, fontsize=7,
                     fontname="hebo", color=NAVY)


def build_page_one(page):
    page_frame(page, "01 / 02", "CIVIC DESIGN")
    put(page, (68, 86, 530, 112),
        "URBAN SYSTEMS LAB  /  FIELD NOTE 07  /  OCTOBER 2025",
        size=7.8, font="hebo", color=ACCENT)

    put(page, (68, 120, 500, 225),
        "Designing Calm\nTechnology for the\nCities of Tomorrow",
        size=28, font="tibo", color=NAVY, lineheight=1.12)

    put(page, (68, 232, 475, 276),
        "How thoughtful interfaces can make urban life quieter, safer and more human.",
        size=11.8, font="helv", color=MUTED, lineheight=1.38)

    page.draw_line(fitz.Point(68, 282), fitz.Point(500, 282), color=ACCENT, width=2.2)
    put(page, (68, 296, 500, 332),
        "A research brief by the Urban Systems Lab. Written for city makers, "
        "service designers and anyone who has waited too long for a pedestrian light.",
        size=9.0, font="helv", color=MUTED, lineheight=1.45)

    # Abstract
    put(page, (68, 354, 190, 374), "ABSTRACT", size=8.2, font="hebo", color=NAVY)
    put(page, (68, 378, 500, 440),
        "Cities are loud not only because of traffic. They are loud because every "
        "surface asks for attention: a screen in the elevator, a ping from the "
        "parking meter, an app that wants us to rate a bench. This brief looks at "
        "what happens when public technology is designed to ask for less.",
        size=9.8, font="helv", color=INK, lineheight=1.42)

    page.draw_line(fitz.Point(68, 458), fitz.Point(500, 458), color=RULE, width=0.6)
    put(page, (68, 472, 260, 500), "The attention tax", size=15.2, font="tibo",
        color=NAVY, lineheight=1.2)
    put(page, (68, 506, 260, 650),
        "Every notification, kiosk and blinking status light takes something from "
        "the people around it. Most of that cost never appears on a budget sheet. "
        "It appears as a parent who misses a train, a visitor who gives up on a "
        "map, or a neighbour who stops reading the noticeboard.\n\n"
        "More information is not the answer. Attention is not a resource that can "
        "be topped up indefinitely; it is a civic condition.",
        size=8.6, font="helv", color=INK, lineheight=1.42)

    put(page, (286, 472, 500, 500), "A quieter interface", size=15.2, font="tibo",
        color=NAVY, lineheight=1.2)
    put(page, (286, 506, 500, 650),
        "Calm technology does not mean technology that disappears. It means "
        "technology that knows when to stop talking. A crossing signal that simply "
        "waits. A library app that opens on the book you were reading, not on a "
        "promotion.\n\n"
        "The shift is small in code and large in culture. It asks teams to measure "
        "the interruptions they remove, not only the features they ship.",
        size=8.6, font="helv", color=INK, lineheight=1.42)

    # Quote panel
    page.draw_rect(fitz.Rect(68, 666, 500, 752), color=None, fill=SOFT)
    page.draw_rect(fitz.Rect(68, 666, 72, 752), color=None, fill=ACCENT)
    put(page, (98, 682, 470, 742),
        "\"The best interface may be the one that asks the least of us -\n"
        "and still leaves us more capable than before.\"",
        size=12.6, font="tiro", color=NAVY, lineheight=1.32)
    put(page, (98, 764, 450, 786),
        "A working principle for public-interest technology.",
        size=8.0, font="helv", color=MUTED)


def build_page_two(page):
    page_frame(page, "02 / 02", "PRINCIPLES")
    put(page, (68, 86, 510, 106), "THREE WORKING PRINCIPLES",
        size=7.8, font="hebo", color=ACCENT)
    put(page, (68, 114, 510, 174),
        "Three principles for quieter systems",
        size=25, font="tibo", color=NAVY, lineheight=1.12)
    put(page, (68, 188, 500, 238),
        "Calm technology is not a style of screen. It is a set of decisions about "
        "when a system should speak, how it should move, and what it should leave "
        "to the person in front of it.",
        size=9.8, font="helv", color=MUTED, lineheight=1.42)

    cards = [
        (
            "1",
            "Speak only when spoken to",
            "A calm system defaults to silence. It does not celebrate every login, "
            "nudge every inactive account or turn a routine confirmation into a "
            "full-screen event. The default state should be quiet enough that a "
            "message means something when it arrives.",
        ),
        (
            "2",
            "Move at the speed of trust",
            "Good urban services arrive on time and then get out of the way. They "
            "show their working, keep a human channel open and never make an "
            "irreversible decision on behalf of someone who has not been asked. "
            "Trust is built in the pauses as much as in the promises.",
        ),
        (
            "3",
            "Leave room for the human",
            "Automation should make the next human action easier, not make it "
            "unnecessary. A form that remembers, a map that admits uncertainty, a "
            "service that hands over cleanly to a person: these are quiet forms of "
            "respect, and they scale better than any notification.",
        ),
    ]
    y = 260
    for number, title, body in cards:
        page.draw_line(fitz.Point(68, y), fitz.Point(500, y), color=RULE, width=0.8)
        page.draw_circle(fitz.Point(86, y + 37), 13, color=None, fill=ACCENT)
        page.insert_text((81.5, y + 41.5), number, fontsize=11,
                         fontname="hebo", color=(1, 1, 1))
        put(page, (116, y + 18, 500, y + 52), title, size=14.6, font="tibo",
            color=NAVY, lineheight=1.2)
        put(page, (116, y + 58, 500, y + 128), body, size=9.2, font="helv",
            color=INK, lineheight=1.42)
        y += 146

    page.draw_rect(fitz.Rect(68, 704, 500, 772), color=None, fill=SOFT)
    put(page, (88, 720, 482, 762),
        "A city feels calm when its systems remember that people are not tasks.",
        size=12.2, font="tiro", color=NAVY, lineheight=1.35)
    put(page, (68, 790, 500, 812),
        "Urban Systems Lab  /  hello@urbansystems.example  /  Shared for discussion.",
        size=7.8, font="helv", color=MUTED)


def main():
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    doc = fitz.open()
    page1 = doc.new_page(width=595, height=842)
    build_page_one(page1)
    page2 = doc.new_page(width=595, height=842)
    build_page_two(page2)
    doc.set_metadata({
        "title": "Designing Calm Technology for the Cities of Tomorrow",
        "author": "Urban Systems Lab",
        "subject": "Civic design research brief",
        "creator": "YiPage PDF demo",
    })
    doc.save(OUT, garbage=4, deflate=True)
    doc.close()
    print(f"Wrote {OUT} ({os.path.getsize(OUT)} bytes)")


if __name__ == "__main__":
    main()

