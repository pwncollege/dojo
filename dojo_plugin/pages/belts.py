from flask import Blueprint, Response, render_template, abort

from ..utils.awards import get_belts


belts = Blueprint("pwncollege_belts", __name__)


@belts.route("/belts")
def view_belts():
    return render_template("belts.html", belt_data=get_belts())


@belts.route("/belt/<color>.svg")
def view_belt(color):
    colors = {
        "white": ("#f0f0f0", "#8f8f8f", "#ababab", "#000000"),
        "orange": ("#ff7f32", "#994c1e", "#b25923", "#000000"),
        "yellow": ("#ffc627", "#997717", "#b28a1b", "#000000"),
        "green": ("#78be20", "#487213", "#548516", "#000000"),
        "blue": ("#00a3e0", "#0b6384", "#0f739b", "#000000"),
        "black": ("#111111", "#000000", "#080808", "#222222"),
    }
    if color not in colors:
        abort(404)

    left, right, center, outline = colors[color]
    svg_content = render_template("components/belt.svg", outline=outline, left=left, right=right, center=center)
    headers = {
        "Cache-Control": "public, max-age=300",
        "Content-Type": "image/svg+xml"
    }
    return Response(svg_content, status=200, headers=headers)
