import io
import json
from datetime import datetime
from typing import Any, Dict, List, Tuple

import streamlit as st
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.enums import TA_CENTER
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, PageBreak, Flowable, Image
from reportlab.pdfgen import canvas
from reportlab.lib.units import mm

# ---------------------------- Streamlit UI ---------------------------- #

st.set_page_config(page_title="Hermione — Arborescence PDF", page_icon="📚", layout="centered")

st.title("📚 Hermione — Arborescence → PDF")
st.caption("Uploader un ou plusieurs JSON. Générer un PDF paginé (≥ 1 fac par page), titres en violet, matières ↦ cours.")

with st.sidebar:
    st.header("🎨 Charte graphique")
    primary_hex = st.color_picker("Couleur principale (titres/bandeau)", "#8c91ea")
    text_hex = st.color_picker("Couleur texte", "#222222")
    brand_img = st.file_uploader("Bandeau / logo (optionnel)", type=["png", "jpg", "jpeg"])
    show_cover = st.checkbox("Ajouter une page de couverture", value=True)
    title_text = st.text_input("Titre de couverture", "hermione Arborescence")
    generate_btn_top = st.button("🔧 Générer le PDF")

st.subheader("1) Uploade tes fichiers JSON")
files = st.file_uploader("Fichiers JSON", type=["json"], accept_multiple_files=True)

# ---------------------- Helpers ----------------------- #

def ensure_list(x: Any) -> List[Any]:
    if x is None:
        return []
    return x if isinstance(x, list) else [x]

def node_title(node: Dict[str, Any]) -> str:
    t = node.get("title") or node.get("data", {}).get("name") or f"Élément {node.get('id','?')}"
    return str(t).strip()

def load_all_trees(files) -> List[Dict[str, Any]]:
    trees: List[Dict[str, Any]] = []
    for f in files:
        try:
            data = json.loads(f.read().decode("utf-8"))
            tree = data.get("data", {}).get("hierarchicalTreeData", [])
            if isinstance(tree, list):
                trees.extend(tree)
        except Exception as e:
            st.warning(f"⚠️ Impossible de lire {getattr(f,'name','(sans nom)')} : {e}")
    return trees

def hex_to_rgb01(hex_color: str) -> tuple[float, float, float]:
    hex_color = hex_color.lstrip("#")
    return (int(hex_color[0:2], 16)/255.0,
            int(hex_color[2:4], 16)/255.0,
            int(hex_color[4:6], 16)/255.0)

def has_any_course(root: Dict[str, Any]) -> bool:
    stack = [root]
    while stack:
        n = stack.pop()
        if n.get("type") == "cours":
            return True
        stack.extend(ensure_list(n.get("children")))
    return False

def collect_matieres_and_courses(fac: Dict[str, Any]) -> List[Tuple[str, List[str]]]:
    """
    Détecte les 'matières' comme:
      - nœuds type 'ue' avec isFolder == False
      - nœuds type 'category'
    Puis collecte tous les descendants 'cours' de chaque matière.
    Renvoie [(label_matiere, [cours triés]), ...] en conservant l'ordre de parcours.
    """
    matieres: List[Tuple[str, List[str]]] = []
    stack = ensure_list(fac.get("children"))
    while stack:
        n = stack.pop(0)  # parcours en largeur pour respecter l'ordre visuel
        tp = n.get("type")
        is_folder = bool(n.get("isFolder", False))

        is_matiere = (tp == "ue" and not is_folder) or (tp == "category")
        if is_matiere:
            cours: List[str] = []
            sub = [n]
            while sub:
                m = sub.pop()
                if m.get("type") == "cours":
                    cours.append(node_title(m))
                else:
                    sub.extend(ensure_list(m.get("children")))
            cours = sorted(set(cours), key=lambda s: s.lower())
            if cours:
                matieres.append((node_title(n), cours))
        else:
            stack.extend(ensure_list(n.get("children")))
    return matieres

# --------------------------- PDF ----------------------------- #

class HeaderBand(Flowable):
    def __init__(self, height_mm: float, primary_rgb: tuple[float, float, float], brand_path: io.BytesIO | None):
        super().__init__()
        self.h = height_mm * mm
        self.primary = primary_rgb
        self.brand_path = brand_path

    def draw(self):
        c: canvas.Canvas = self.canv
        width, height = c._pagesize
        c.saveState()
        c.setFillColorRGB(*self.primary)
        c.rect(0, height - self.h, width, self.h, stroke=0, fill=1)
        if self.brand_path:
            try:
                margin = 8 * mm
                max_h = self.h - 6 * mm
                img = Image(self.brand_path, width=width - 2*margin, height=max_h)
                iw, ih = img.wrap(width - 2*margin, max_h)
                img.drawOn(c, (width - iw) / 2, height - self.h + (self.h - ih) / 2)
            except Exception:
                pass
        c.restoreState()

def add_style_if_absent(styles, style: ParagraphStyle):
    if style.name not in styles.byName:
        styles.add(style)

def build_pdf(trees: List[Dict[str, Any]],
              primary_hex: str,
              text_hex: str,
              brand_img_bytes: bytes | None,
              title_text: str,
              show_cover: bool) -> bytes:
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        leftMargin=18*mm, rightMargin=18*mm, topMargin=20*mm, bottomMargin=18*mm
    )

    primary_rgb01 = hex_to_rgb01(primary_hex)

    styles = getSampleStyleSheet()

    # TITRES EN VIOLET (couleur principale)
    add_style_if_absent(styles, ParagraphStyle(
        name="CoverTitle",
        fontName="Helvetica-Bold",
        fontSize=28,
        alignment=TA_CENTER,
        textColor=primary_hex,
        leading=32,
    ))
    add_style_if_absent(styles, ParagraphStyle(
        name="FacTitle",
        fontName="Helvetica-Bold",
        fontSize=22,
        textColor=primary_hex,
        leading=26,
        spaceAfter=6,
    ))
    add_style_if_absent(styles, ParagraphStyle(
        name="SectionTitle",
        fontName="Helvetica-Bold",
        fontSize=15,
        textColor=primary_hex,
        leading=18,
        spaceBefore=6,
        spaceAfter=2,
    ))
    # Corps en couleur de texte
    add_style_if_absent(styles, ParagraphStyle(
        name="ListItem",
        fontName="Helvetica",
        fontSize=11.5,
        textColor=text_hex,
        leading=15,
        leftIndent=10,
    ))

    story: List[Any] = []

    # -- Couverture
    if show_cover:
        band = HeaderBand(height_mm=28, primary_rgb=primary_rgb01,
                          brand_path=io.BytesIO(brand_img_bytes) if brand_img_bytes else None)
        story.append(band)
        story.append(Spacer(1, 22 * mm))
        story.append(Paragraph(title_text, styles["CoverTitle"]))
        story.append(Spacer(1, 8 * mm))
        today = datetime.now().strftime("%d %B %Y")
        story.append(Paragraph(f"Généré le {today}", ParagraphStyle(name="CoverMeta", textColor=text_hex, alignment=TA_CENTER)))
        story.append(PageBreak())

    # -- Filtrer les facs sans aucun cours
    facs_effectives = []
    for fac in trees:
        if has_any_course(fac):
            facs_effectives.append(fac)

    # -- Contenu : 1 fac minimum par page
    for idx, fac in enumerate(facs_effectives):
        band = HeaderBand(height_mm=16, primary_rgb=primary_rgb01,
                          brand_path=io.BytesIO(brand_img_bytes) if brand_img_bytes else None)
        story.append(band)
        story.append(Spacer(1, 10 * mm))

        fac_name = node_title(fac)
        story.append(Paragraph(fac_name, styles["FacTitle"]))

        matieres = collect_matieres_and_courses(fac)

        if not matieres:
            # Si on arrive ici, c'est que la fac avait des cours “hors matière” détectés par has_any_course,
            # mais aucune matière éligible. On affiche au moins les cours orphelins groupés sous "Autres".
            # Collecte cours globaux:
            orphan_courses: List[str] = []
            stack = ensure_list(fac.get("children"))
            while stack:
                n = stack.pop()
                if n.get("type") == "cours":
                    orphan_courses.append(node_title(n))
                else:
                    stack.extend(ensure_list(n.get("children")))
            orphan_courses = sorted(set(orphan_courses), key=lambda s: s.lower())
            if orphan_courses:
                story.append(Paragraph("Autres", styles["SectionTitle"]))
                for ct in orphan_courses:
                    story.append(Paragraph(f"• {ct}", styles["ListItem"]))
        else:
            for mat_label, cours in matieres:
                story.append(Paragraph(mat_label, styles["SectionTitle"]))
                for ctitle in cours:
                    story.append(Paragraph(f"• {ctitle}", styles["ListItem"]))
                story.append(Spacer(1, 3 * mm))

        if idx < len(facs_effectives) - 1:
            story.append(PageBreak())

    doc.build(story)
    buf.seek(0)
    return buf.read()

# ---------------------------- Main action ---------------------------- #

if files:
    trees = load_all_trees(files)
    total_facs = len(trees)
    facs_with_courses = [t for t in trees if has_any_course(t)]
    skipped = total_facs - len(facs_with_courses)

    st.success(f"✅ {len(facs_with_courses)} faculté(s) avec cours détectée(s).")
    if skipped > 0:
        st.info(f"ℹ️ {skipped} faculté(s) sans cours ont été ignorées.")

    with st.expander("Aperçu (facultés retenues)"):
        for i, fac in enumerate(facs_with_courses, start=1):
            st.write(f"{i}. {node_title(fac)}")

    if st.button("📄 Générer le PDF") or generate_btn_top:
        brand_bytes = brand_img.read() if brand_img else None
        pdf_bytes = build_pdf(
            trees=trees,
            primary_hex=primary_hex,
            text_hex=text_hex,
            brand_img_bytes=brand_bytes,
            title_text=title_text,
            show_cover=show_cover,
        )
        st.download_button(
            "⬇️ Télécharger le PDF",
            data=pdf_bytes,
            file_name="hermione_arborescence.pdf",
            mime="application/pdf",
        )
else:
    st.info("Charge au moins un JSON pour continuer.")
