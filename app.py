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
st.caption("Uploader un ou plusieurs JSON (~30 000 lignes ok). Générer un PDF propre et paginé (1 fac par page au minimum).")

with st.sidebar:
    st.header("🎨 Charte graphique")
    primary_hex = st.color_picker("Couleur principale", "#8c91ea")
    text_hex = st.color_picker("Couleur texte", "#222222")
    brand_img = st.file_uploader("Bandeau / logo (optionnel)", type=["png", "jpg", "jpeg"])
    show_cover = st.checkbox("Ajouter une page de couverture", value=True)
    title_text = st.text_input("Titre de couverture", "hermione Arborescence")
    generate_btn_top = st.button("🔧 Générer le PDF")

st.subheader("1) Uploade tes fichiers JSON")
files = st.file_uploader("Fichiers JSON", type=["json"], accept_multiple_files=True)

# ---------------------- Parsing & tree helpers ----------------------- #

def ensure_list(x: Any) -> List[Any]:
    if x is None:
        return []
    if isinstance(x, list):
        return x
    return [x]

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

def node_title(node: Dict[str, Any]) -> str:
    t = node.get("title") or node.get("data", {}).get("name") or f"Élément {node.get('id','?')}"
    return str(t).strip()

def collect_courses_by_matiere(root_node: Dict[str, Any]) -> List[Tuple[str, List[str]]]:
    """
    À partir d'une fac (racine), renvoie [(matiere_label, [cours...]), ...]
    Les 'cours' = tous les descendants avec type == 'cours'.
    """
    out: List[Tuple[str, List[str]]] = []
    for child in ensure_list(root_node.get("children")):
        matiere_label = node_title(child)
        cours_list: List[str] = []

        stack = [child]
        while stack:
            n = stack.pop()
            if n.get("type") == "cours":
                cours_list.append(node_title(n))
            else:
                stack.extend(ensure_list(n.get("children")))
        out.append((matiere_label, sorted(set(cours_list), key=lambda s: s.lower())))
    return out

# --------------------------- PDF Builder ----------------------------- #

class HeaderBand(Flowable):
    """Bandeau d'en-tête pleine largeur avec couleur principale et (optionnellement) une image."""
    def __init__(self, height_mm: float, primary_rgb: Tuple[float, float, float], brand_path: io.BytesIO | None):
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

def hex_to_rgb01(hex_color: str) -> Tuple[float, float, float]:
    hex_color = hex_color.lstrip("#")
    return (int(hex_color[0:2], 16)/255.0,
            int(hex_color[2:4], 16)/255.0,
            int(hex_color[4:6], 16)/255.0)

def add_style_if_absent(styles, style: ParagraphStyle):
    # évite KeyError si le nom existe déjà
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

    add_style_if_absent(styles, ParagraphStyle(
        name="CoverTitle",
        fontName="Helvetica-Bold",
        fontSize=28,
        alignment=TA_CENTER,
        textColor=text_hex,
        leading=32,
    ))

    add_style_if_absent(styles, ParagraphStyle(
        name="FacTitle",
        fontName="Helvetica-Bold",
        fontSize=22,
        textColor=text_hex,
        leading=26,
        spaceAfter=6,
    ))

    add_style_if_absent(styles, ParagraphStyle(
        name="SectionTitle",
        fontName="Helvetica-Bold",
        fontSize=15,
        textColor=text_hex,
        leading=18,
        spaceBefore=6,
        spaceAfter=2,
    ))

    # ⚠️ nouveau nom pour éviter la collision avec le style "Bullet" de base
    add_style_if_absent(styles, ParagraphStyle(
        name="ListItem",
        fontName="Helvetica",
        fontSize=11.5,
        textColor=text_hex,
        leading=15,
        leftIndent=10,
    ))

    story: List[Any] = []

    # -- Page de couverture
    if show_cover:
        band = HeaderBand(height_mm=28, primary_rgb=primary_rgb01,
                          brand_path=io.BytesIO(brand_img_bytes) if brand_img_bytes else None)
        story.append(band)
        story.append(Spacer(1, 22 * mm))
        story.append(Paragraph(title_text, styles["CoverTitle"]))
        story.append(Spacer(1, 8 * mm))
        today = datetime.now().strftime("%d %B %Y")
        story.append(Paragraph(f"Généré le {today}", ParagraphStyle(name="CoverMeta", alignment=TA_CENTER)))
        story.append(PageBreak())

    # -- Contenu : 1 fac par page minimum (une fac peut s'étendre sur plusieurs pages)
    for idx, fac in enumerate(trees):
        # entête graphique en haut de la première page de la fac
        band = HeaderBand(height_mm=16, primary_rgb=primary_rgb01,
                          brand_path=io.BytesIO(brand_img_bytes) if brand_img_bytes else None)
        story.append(band)
        story.append(Spacer(1, 10 * mm))

        fac_name = node_title(fac)
        story.append(Paragraph(fac_name, styles["FacTitle"]))

        matieres = collect_courses_by_matiere(fac)

        if not matieres:
            story.append(Paragraph("• Aucune matière/cours trouvé(e) pour cette faculté.", styles["ListItem"]))
        else:
            for mat_label, cours in matieres:
                story.append(Paragraph(mat_label, styles["SectionTitle"]))
                if cours:
                    for ctitle in cours:
                        story.append(Paragraph(f"• {ctitle}", styles["ListItem"]))
                else:
                    story.append(Paragraph("• (aucun cours listé)", styles["ListItem"]))
                story.append(Spacer(1, 3 * mm))

        # assure qu'aucune autre fac ne commencera sur la même page
        if idx < len(trees) - 1:
            story.append(PageBreak())

    doc.build(story)
    buf.seek(0)
    return buf.read()

# ---------------------------- Main action ---------------------------- #

if files:
    trees = load_all_trees(files)
    nb_fac = len(trees)
    st.success(f"✅ {nb_fac} faculté(s) détectée(s).")
    with st.expander("Aperçu (noms des facultés)"):
        for i, fac in enumerate(trees, start=1):
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
