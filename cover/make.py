"""Render cover/cover.html and screenshot it to cover/gone-gov-cover.jpg (1200x630, like the other landing tiles).

    python3 cover/make.py
The addresses in the background are real ones the live check found gone (DNS, 404 or redirected away).
"""
import subprocess
from pathlib import Path

here = Path(__file__).parent
GONE = [  # (address, status found by the live check)
    ("nca2023.globalchange.gov", "DNS"), ("data.globalchange.gov/report/nca5", "DNS"),
    ("sealevel.globalchange.gov/sea-level-101", "DNS"), ("epa.gov/climate-indicators", "404"),
    ("aidscape.usaid.gov/explore/about", "DNS"), ("ephtracking.cdc.gov/showLifestyleRiskFactorsTracking", "404"),
    ("rems.ed.gov/IHEThreatAssessmentTeams.aspx", "DNS"), ("covid.gov/be-informed", "→ whitehouse.gov"),
    ("health2016.globalchange.gov", "DNS"), ("atsdr.cdc.gov/csem/arsenic/patient_education.html", "404"),
    ("epa.gov/brownfields/types-epa-brownfield-grant-funding", "404"), ("sealevel.globalchange.gov/national-sea-level-explorer", "DNS"),
    ("carbon2018.globalchange.gov", "DNS"), ("community.lincs.ed.gov/group/29/bulletin", "404"),
    ("aidscape.usaid.gov/pse", "DNS"), ("nca2009.globalchange.gov", "DNS"), ("scenarios.globalchange.gov", "DNS"),
    ("wioaplans.ed.gov", "DNS"), ("covid.gov/be-informed/longcovid/about", "→ whitehouse.gov"),
    ("globalchange.gov", "DNS"), ("atlas.globalchange.gov", "DNS"),
]
W, H = 1200, 630
cols = 3
rows = "".join('<li><s>%s</s><b>%s</b></li>' % (g, st) for g, st in GONE)
html = f"""<!doctype html><meta charset=utf-8><style>
html,body{{margin:0;width:{W}px;height:{H}px;overflow:hidden;background:#1d2a44;font-family:-apple-system,Helvetica,sans-serif}}
ul{{position:absolute;inset:26px 30px auto 30px;margin:0;padding:0;list-style:none;columns:{cols};column-gap:34px}}
li{{font:15px/2.05 ui-monospace,Menlo,monospace;color:#8e9ab3;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}}
li s{{text-decoration-color:#f0715f;text-decoration-thickness:2px}}
li b{{font-weight:700;color:#f0715f;margin-left:10px;font-size:12px}}
.panel{{position:absolute;left:70px;right:70px;bottom:54px;background:#f7f4ee;border-top:8px solid #b42318;padding:30px 44px 32px;box-shadow:0 20px 50px rgba(0,0,0,.35)}}
h1{{margin:0;font:700 96px/1 Georgia,serif;color:#1b1f29;letter-spacing:-1px}}
h1 em{{font:700 84px/1 ui-monospace,Menlo,monospace;font-style:normal;color:#b42318;letter-spacing:-3px}}
p{{margin:16px 0 0;font:500 27px/1.3 -apple-system,Helvetica,sans-serif;color:#3d4250}}
p b{{color:#1b1f29}}
</style>
<ul>{rows}</ul>
<div class=panel><h1>Gone from <em>.gov</em></h1>
<p><b>1.5 million</b> archived federal pages, documents and videos, checked against today’s web</p></div>"""
(here / "cover.html").write_text(html)
chrome = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
png = here / "cover.png"
subprocess.run([chrome, "--headless=new", "--hide-scrollbars", "--force-device-scale-factor=1", f"--window-size={W},{H}",
                f"--screenshot={png}", (here / "cover.html").as_uri()], check=True, capture_output=True)
subprocess.run(["sips", "-s", "format", "jpeg", "-s", "formatOptions", "88", str(png), "--out", str(here / "gone-gov-cover.jpg")],
               check=True, capture_output=True)
png.unlink()
print(here / "gone-gov-cover.jpg")
