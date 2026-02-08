import base64
import hashlib
import logging
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession
from app.persistence.models import Book, User, SemanticFunction, SemanticFunctionEmbedding

logger = logging.getLogger(__name__)

# Genre → color palette for generated covers
GENRE_COLORS: dict[str, tuple[str, str]] = {
    "Science Fiction": ("#1e3a5f", "#4a90d9"),
    "Dystopian": ("#4a1942", "#c060a1"),
    "Classic": ("#2d3436", "#636e72"),
    "Fantasy": ("#1b4332", "#40916c"),
    "Cyberpunk": ("#0d0d0d", "#00f0ff"),
    "Romance": ("#6b2737", "#e07c8f"),
    "Coming-of-age": ("#5c4033", "#c4a882"),
    "Magical Realism": ("#4a2c6b", "#a87fd4"),
    "Fiction": ("#1a535c", "#4ecdc4"),
    "Non-fiction": ("#2c3e50", "#3498db"),
    "Post-apocalyptic": ("#3d0c02", "#a0522d"),
    "Gothic": ("#1a0a2e", "#7b2d8e"),
    "Horror": ("#1a0000", "#8b0000"),
    "Self-help": ("#0b3d2e", "#27ae60"),
}


def _generate_book_cover_base64(title: str, author: str, genre: str) -> str:
    """Generate an SVG book cover and return it as a base64 data URI."""
    bg, accent = GENRE_COLORS.get(genre, ("#2c3e50", "#3498db"))

    # Deterministic seed from title for slight variation
    h = int(hashlib.md5(title.encode()).hexdigest()[:6], 16)
    pattern_y = 40 + (h % 60)
    stripe_opacity = 0.08 + (h % 10) / 100

    # Truncate title for display (split into lines)
    words = title.split()
    lines: list[str] = []
    current = ""
    for w in words:
        if len(current + " " + w) > 18:
            lines.append(current.strip())
            current = w
        else:
            current = (current + " " + w).strip()
    if current:
        lines.append(current)
    lines = lines[:4]

    title_svg = ""
    start_y = 100 - (len(lines) * 12)
    for i, line in enumerate(lines):
        escaped = line.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        title_svg += (
            f'<text x="75" y="{start_y + i * 26}" '
            f'font-family="Georgia,serif" font-size="16" font-weight="bold" '
            f'fill="white" text-anchor="middle">{escaped}</text>'
        )

    author_short = author if len(author) <= 22 else author[:20] + "..."
    author_escaped = author_short.replace("&", "&amp;").replace("<", "&lt;")

    svg = f'''<svg xmlns="http://www.w3.org/2000/svg" width="150" height="220" viewBox="0 0 150 220">
  <defs>
    <linearGradient id="bg" x1="0%" y1="0%" x2="100%" y2="100%">
      <stop offset="0%" style="stop-color:{bg}"/>
      <stop offset="100%" style="stop-color:{accent}"/>
    </linearGradient>
  </defs>
  <rect width="150" height="220" rx="4" fill="url(#bg)"/>
  <rect x="0" y="{pattern_y}" width="150" height="3" fill="white" opacity="{stripe_opacity}"/>
  <rect x="0" y="{pattern_y + 40}" width="150" height="1" fill="white" opacity="{stripe_opacity}"/>
  <rect x="0" y="{pattern_y + 80}" width="150" height="2" fill="white" opacity="{stripe_opacity + 0.03}"/>
  <rect x="12" y="20" width="126" height="155" rx="2" fill="white" opacity="0.07"/>
  {title_svg}
  <line x1="40" y1="{start_y + len(lines) * 26 + 2}" x2="110" y2="{start_y + len(lines) * 26 + 2}" stroke="white" stroke-opacity="0.4" stroke-width="1"/>
  <text x="75" y="198" font-family="Arial,sans-serif" font-size="10" fill="white" fill-opacity="0.75" text-anchor="middle">{author_escaped}</text>
  <rect x="0" y="0" width="6" height="220" rx="4" fill="black" opacity="0.15"/>
</svg>'''

    encoded = base64.b64encode(svg.encode("utf-8")).decode("utf-8")
    return f"data:image/svg+xml;base64,{encoded}"

BOOKS_DATA = [
    {
        "title": "Dune",
        "author": "Frank Herbert",
        "genre": "Ciencia Ficción",
        "price": 15.99,
        "stock": 25,
        "description": "Una obra fundamental de la ciencia ficción que explora el poder político, la religión, la ecología y la lucha por el control de un recurso vital en el planeta desértico Arrakis, donde cada decisión tiene consecuencias a escala galáctica."
    },
    {
        "title": "1984",
        "author": "George Orwell",
        "genre": "Distopía",
        "price": 12.50,
        "stock": 40,
        "description": "Una novela distópica que retrata una sociedad sometida a un régimen totalitario, donde la vigilancia constante, la manipulación del lenguaje y la supresión del pensamiento crítico definen la vida cotidiana."
    },
    {
        "title": "El Gran Gatsby",
        "author": "F. Scott Fitzgerald",
        "genre": "Clásico",
        "price": 10.99,
        "stock": 30,
        "description": "Un retrato crítico del sueño americano ambientado en la era del jazz, donde la riqueza, el amor idealizado y la decadencia moral se entrelazan en una historia marcada por la ilusión y la tragedia."
    },
    {
        "title": "Matar a un ruiseñor",
        "author": "Harper Lee",
        "genre": "Clásico",
        "price": 11.99,
        "stock": 35,
        "description": "Una historia profunda sobre la injusticia racial y la pérdida de la inocencia, narrada desde la perspectiva de una niña que observa cómo el prejuicio afecta a su comunidad en el sur de Estados Unidos."
    },
    {
        "title": "El Hobbit",
        "author": "J.R.R. Tolkien",
        "genre": "Fantasía",
        "price": 14.99,
        "stock": 20,
        "description": "Una aventura fantástica que sigue a Bilbo Bolsón, un hobbit común que se ve envuelto en una peligrosa misión llena de criaturas míticas, tesoros ocultos y decisiones que cambiarán su destino."
    },
    {
        "title": "Neuromante",
        "author": "William Gibson",
        "genre": "Cyberpunk",
        "price": 13.50,
        "stock": 15,
        "description": "Una novela icónica del cyberpunk que presenta un futuro dominado por la tecnología, las corporaciones y el ciberespacio, donde los hackers navegan entre realidades virtuales y conspiraciones globales."
    },
    {
        "title": "Orgullo y Prejuicio",
        "author": "Jane Austen",
        "genre": "Romance",
        "price": 9.99,
        "stock": 50,
        "description": "Una novela romántica y social que examina el matrimonio, las clases sociales y el orgullo personal a través de la relación entre Elizabeth Bennet y el reservado señor Darcy."
    },
    {
        "title": "El guardián entre el centeno",
        "author": "J.D. Salinger",
        "genre": "Crecimiento personal / Juvenil",
        "price": 11.50,
        "stock": 28,
        "description": "La historia de un adolescente que deambula por Nueva York mientras enfrenta su confusión, alienación y rechazo hacia la hipocresía del mundo adulto."
    },
    {
        "title": "Un mundo feliz",
        "author": "Aldous Huxley",
        "genre": "Distopía",
        "price": 12.99,
        "stock": 22,
        "description": "Una visión inquietante de una sociedad futura donde la estabilidad se mantiene mediante el control biológico, el condicionamiento psicológico y la eliminación del sufrimiento individual."
    },
    {
        "title": "El Señor de los Anillos",
        "author": "J.R.R. Tolkien",
        "genre": "Fantasía",
        "price": 29.99,
        "stock": 18,
        "description": "Una epopeya de fantasía que narra la lucha entre el bien y el mal en la Tierra Media, centrada en una peligrosa misión para destruir un anillo de poder absoluto."
    },
    {
        "title": "Fahrenheit 451",
        "author": "Ray Bradbury",
        "genre": "Distopía",
        "price": 11.00,
        "stock": 33,
        "description": "Una novela que presenta un futuro donde los libros están prohibidos y son quemados, explorando el valor del conocimiento, la memoria y la libertad intelectual."
    },
    {
        "title": "Cien años de soledad",
        "author": "Gabriel García Márquez",
        "genre": "Realismo Mágico",
        "price": 14.50,
        "stock": 20,
        "description": "Una saga familiar que recorre varias generaciones en el pueblo ficticio de Macondo, combinando lo cotidiano con lo mágico para explorar el tiempo, la soledad y el destino."
    },
    {
        "title": "El Alquimista",
        "author": "Paulo Coelho",
        "genre": "Ficción / Filosófico",
        "price": 10.50,
        "stock": 45,
        "description": "Una novela de carácter filosófico que sigue el viaje de un joven pastor en busca de su propósito personal, resaltando la importancia de perseguir los propios sueños."
    },
    {
        "title": "Crimen y Castigo",
        "author": "Fyodor Dostoevsky",
        "genre": "Clásico",
        "price": 13.99,
        "stock": 16,
        "description": "Un intenso estudio psicológico sobre la culpa, la moral y la redención, centrado en un joven que comete un crimen y enfrenta las consecuencias internas de sus actos."
    },
    {
        "title": "Guía del autoestopista galáctico",
        "author": "Douglas Adams",
        "genre": "Ciencia Ficción",
        "price": 12.00,
        "stock": 30,
        "description": "Una comedia de ciencia ficción irreverente que mezcla humor absurdo con aventuras espaciales, ofreciendo una sátira sobre la vida, el universo y todo lo demás."
    },
    {
        "title": "Sapiens: De animales a dioses",
        "author": "Yuval Noah Harari",
        "genre": "No ficción",
        "price": 18.99,
        "stock": 24,
        "description": "Un recorrido accesible y provocador por la historia de la humanidad, desde los primeros homínidos hasta las sociedades modernas y los desafíos del futuro."
    },
    {
        "title": "El nombre del viento",
        "author": "Patrick Rothfuss",
        "genre": "Fantasía",
        "price": 16.99,
        "stock": 19,
        "description": "La narración de la vida de un músico y mago legendario que relata su propia historia, combinando misterio, magia y una construcción de mundo detallada."
    },
    {
        "title": "Fundación",
        "author": "Isaac Asimov",
        "genre": "Ciencia Ficción",
        "price": 14.00,
        "stock": 21,
        "description": "Una saga de ciencia ficción que analiza el colapso y la reconstrucción de una civilización galáctica a través de la ciencia, la política y la psicohistoria."
    },
    {
        "title": "Don Quijote de la Mancha",
        "author": "Miguel de Cervantes",
        "genre": "Clásico",
        "price": 12.99,
        "stock": 15,
        "description": "Una obra fundamental de la literatura que sigue las aventuras de un caballero idealista y su fiel escudero, explorando la frontera entre la realidad y la fantasía."
    },
    {
        "title": "El Marciano",
        "author": "Andy Weir",
        "genre": "Ciencia Ficción",
        "price": 13.99,
        "stock": 27,
        "description": "Una historia de supervivencia científica donde un astronauta debe usar su ingenio y conocimientos técnicos para sobrevivir solo en el planeta Marte."
    },
    {
        "title": "Harry Potter y la piedra filosofal",
        "author": "J.K. Rowling",
        "genre": "Fantasía",
        "price": 12.99,
        "stock": 60,
        "description": "El inicio de una saga fantástica que introduce a un joven mago en un mundo oculto lleno de hechizos, amistades, misterios y desafíos."
    },
    {
        "title": "La Carretera",
        "author": "Cormac McCarthy",
        "genre": "Post-apocalíptico",
        "price": 11.99,
        "stock": 14,
        "description": "Un relato sombrío y emotivo sobre un padre y su hijo que atraviesan un mundo devastado, aferrándose al amor y la esperanza en medio del caos."
    },
    {
        "title": "Hábitos Atómicos",
        "author": "James Clear",
        "genre": "Autoayuda",
        "price": 16.00,
        "stock": 35,
        "description": "Un libro práctico que explica cómo pequeños cambios consistentes pueden generar mejoras significativas en la vida personal y profesional."
    },
    {
        "title": "Kafka en la orilla",
        "author": "Haruki Murakami",
        "genre": "Realismo Mágico",
        "price": 15.00,
        "stock": 17,
        "description": "Una novela surrealista que entrelaza dos historias aparentemente inconexas, explorando la identidad, el destino y la memoria."
    },
    {
        "title": "Snow Crash",
        "author": "Neal Stephenson",
        "genre": "Cyberpunk",
        "price": 14.50,
        "stock": 13,
        "description": "Una obra cyberpunk que mezcla acción, sátira y cultura digital, presentando un futuro dominado por realidades virtuales y corporaciones poderosas."
    },
    {
        "title": "Pensar rápido, pensar despacio",
        "author": "Daniel Kahneman",
        "genre": "No ficción",
        "price": 17.50,
        "stock": 20,
        "description": "Un análisis profundo sobre cómo funciona la mente humana, explicando los dos sistemas de pensamiento que influyen en nuestras decisiones."
    },
    # --- Casos adicionales (Duplicados/Variaciones para aumentar la lista) ---
    {
        "title": "Crónicas Marcianas",
        "author": "Ray Bradbury",
        "genre": "Ciencia Ficción",
        "price": 13.00,
        "stock": 18,
        "description": "Un clásico que relata la llegada de los humanos a Marte y la colonización del planeta rojo a través de una serie de relatos interconectados."
    },
    {
        "title": "El Retrato de Dorian Gray",
        "author": "Oscar Wilde",
        "genre": "Clásico / Gótico",
        "price": 10.99,
        "stock": 25,
        "description": "La historia de un joven que permanece eternamente bello mientras su retrato envejece y refleja la corrupción de su alma."
    },
    {
        "title": "El Resplandor",
        "author": "Stephen King",
        "genre": "Terror",
        "price": 15.50,
        "stock": 30,
        "description": "Un hombre se convierte en el cuidador de un hotel aislado durante el invierno, donde fuerzas sobrenaturales acechan a su familia."
    },
    {
        "title": "Mundo Anillo",
        "author": "Larry Niven",
        "genre": "Ciencia Ficción",
        "price": 14.99,
        "stock": 12,
        "description": "Una expedición viaja a un gigantesco mundo artificial en forma de anillo, descubriendo secretos de una civilización olvidada."
    },
    # ... continuación de BOOKS_DATA
    {
        "title": "Cresta de la ola",
        "author": "Thomas Pynchon",
        "genre": "Ficción Contemporánea",
        "price": 18.50,
        "stock": 10,
        "description": "Una novela que mezcla la paranoia tecnológica tras el estallido de la burbuja puntocom con tramas de espionaje en la Nueva York previa al 11 de septiembre."
    },
    {
        "title": "La sombra del viento",
        "author": "Carlos Ruiz Zafón",
        "genre": "Misterio",
        "price": 16.90,
        "stock": 42,
        "description": "Un joven es llevado por su padre a un lugar secreto llamado el Cementerio de los Libros Olvidados, desencadenando una historia de amor, traición y secretos oscuros."
    },
    {
        "title": "Crónica de una muerte anunciada",
        "author": "Gabriel García Márquez",
        "genre": "Realismo Mágico",
        "price": 9.99,
        "stock": 55,
        "description": "Una reconstrucción casi periodística de un asesinato en un pueblo donde todos sabían que iba a ocurrir, pero nadie hizo nada para evitarlo."
    },
    {
        "title": "El cuento de la criada",
        "author": "Margaret Atwood",
        "genre": "Distopía",
        "price": 13.20,
        "stock": 29,
        "description": "En una sociedad teocrática y totalitaria, las pocas mujeres fértiles son forzadas a la servidumbre reproductiva bajo un control absoluto."
    },
    {
        "title": "La comunidad del anillo",
        "author": "J.R.R. Tolkien",
        "genre": "Fantasía",
        "price": 22.00,
        "stock": 15,
        "description": "El primer tomo de la gran saga donde Frodo Bolsón comienza su viaje para destruir el Anillo Único antes de que caiga en manos del Señor Oscuro."
    },
    {
        "title": "Steve Jobs",
        "author": "Walter Isaacson",
        "genre": "Biografía",
        "price": 21.00,
        "stock": 12,
        "description": "La crónica definitiva de la vida del cofundador de Apple, basada en más de cuarenta entrevistas realizadas al genio tecnológico a lo largo de dos años."
    },
    {
        "title": "Ready Player One",
        "author": "Ernest Cline",
        "genre": "Ciencia Ficción",
        "price": 14.50,
        "stock": 38,
        "description": "En un futuro distópico, la humanidad vive dentro de una simulación virtual de realidad aumentada llamada OASIS, donde se esconde un tesoro incalculable."
    },
    {
        "title": "Los juegos del hambre",
        "author": "Suzanne Collins",
        "genre": "Juvenil / Distopía",
        "price": 12.99,
        "stock": 60,
        "description": "En las ruinas de lo que fue Norteamérica, cada año se obliga a jóvenes a participar en un evento televisado donde solo uno puede sobrevivir."
    },
    {
        "title": "Drácula",
        "author": "Bram Stoker",
        "genre": "Terror / Clásico",
        "price": 11.00,
        "stock": 22,
        "description": "La famosa novela epistolar que definió el mito del vampiro moderno a través del viaje del conde Drácula desde Transilvania hasta Londres."
    },
    {
        "title": "Frankenstein",
        "author": "Mary Shelley",
        "genre": "Ciencia Ficción / Terror",
        "price": 10.50,
        "stock": 19,
        "description": "Un científico desafía las leyes de la naturaleza al crear vida a partir de materia inanimada, enfrentándose luego al horror de su propia creación."
    },
    {
        "title": "El código Da Vinci",
        "author": "Dan Brown",
        "genre": "Suspenso",
        "price": 14.95,
        "stock": 45,
        "description": "Un experto en simbología se ve envuelto en una conspiración milenaria que involucra a la Iglesia y un secreto oculto en las obras de Leonardo da Vinci."
    },
    {
        "title": "El nombre de la rosa",
        "author": "Umberto Eco",
        "genre": "Misterio Histórico",
        "price": 15.80,
        "stock": 14,
        "description": "Un fraile franciscano investiga una serie de misteriosas muertes en una abadía benedictina del siglo XIV, rodeado de intrigas religiosas y libros prohibidos."
    },
    {
        "title": "El Psicoanalista",
        "author": "John Katzenbach",
        "genre": "Thriller",
        "price": 13.90,
        "stock": 26,
        "description": "Un psicoanalista recibe una nota de un desconocido que amenaza con destruir su vida a menos que logre descubrir quién es el autor en quince días."
    },
    {
        "title": "Crónicas de la Dragonlance",
        "author": "Margaret Weis y Tracy Hickman",
        "genre": "Fantasía",
        "price": 17.50,
        "stock": 11,
        "description": "Un grupo de amigos se reúne tras años de separación para descubrir que la guerra y los dragones han regresado al mundo de Krynn."
    },
    {
        "title": "Ensayo sobre la ceguera",
        "author": "José Saramago",
        "genre": "Ficción",
        "price": 14.00,
        "stock": 20,
        "description": "Una epidemia de ceguera blanca se extiende por una ciudad, revelando lo más oscuro y lo más noble de la naturaleza humana bajo una presión extrema."
    },
    {
        "title": "Anna Karenina",
        "author": "Leo Tolstoy",
        "genre": "Clásico / Drama",
        "price": 16.00,
        "stock": 8,
        "description": "Una compleja exploración del amor, la infidelidad y la sociedad rusa del siglo XIX a través de la trágica vida de su protagonista."
    },
    {
        "title": "Siddhartha",
        "author": "Hermann Hesse",
        "genre": "Ficción Filosófica",
        "price": 9.50,
        "stock": 33,
        "description": "El viaje espiritual de un hombre en la India antigua que busca la iluminación a través de la experiencia personal, el ascetismo y la sabiduría."
    },
    {
        "title": "Homo Deus",
        "author": "Yuval Noah Harari",
        "genre": "No ficción",
        "price": 19.99,
        "stock": 21,
        "description": "Una mirada hacia el futuro de la humanidad, explorando cómo la tecnología y la biotecnología podrían convertirnos en seres con capacidades divinas."
    },
    {
        "title": "La invención de Morel",
        "author": "Adolfo Bioy Casares",
        "genre": "Ciencia Ficción",
        "price": 12.00,
        "stock": 15,
        "description": "Un fugitivo llega a una isla desierta donde descubre una extraña máquina que proyecta imágenes eternas, difuminando la realidad y la ficción."
    },
    {
        "title": "Los pilares de la Tierra",
        "author": "Ken Follett",
        "genre": "Novela Histórica",
        "price": 18.90,
        "stock": 30,
        "description": "La construcción de una catedral gótica sirve como eje para narrar las vidas de diversos personajes en la Inglaterra medieval, llena de guerra y ambición."
    }
]

SEMANTIC_FUNCTIONS = [
    {
        "name": "search_books_for_sale",
        "description": (
            "Buscar libros disponibles en la tienda según diferentes criterios como título, autor, "
            "género literario, temática, palabras clave o intereses generales del usuario. "
            "Esta función se utiliza cuando el usuario quiere explorar el catálogo sin referirse "
            "a un libro específico, sino a una categoría o tipo de libro."
        ),
        "examples": [
            "qué libros tienen disponibles",
            "muéstrame libros de ciencia ficción",
            "busco novelas de fantasía",
            "libros sobre inteligencia artificial",
            "qué libros recomiendan de terror",
            "quiero ver libros de programación",
            "tienen libros de historia",
            "buscar libros de romance",
            "libros parecidos a ciencia ficción distópica",
            "qué opciones de libros hay en la tienda",
            
            
            
            "¿Qué tienen para leer hoy?",
            "Muéstrame el catálogo de este género",
            "Busco novelas de este tipo",
            "¿Tienen algo sobre esta temática?",
            "Enséñame los títulos que tengan disponibles",
            "Quiero ver qué opciones hay en esta categoría",
            "¿Hay algún texto sobre este asunto técnico?",
            "Listado de obras de esta corriente literaria",
            "Busca algo parecido a estas temáticas",
            "¿Qué géneros manejan en la tienda?",
            "Dame opciones de este estilo de lectura",
            "¿Tienen ejemplares de este tópico?",
            "Busco lecturas sobre este campo de estudio"
        ],
    },
    {
        "name": "recommend_books_for_purchase",
        "description": (
            "Recomendar libros al usuario en función de sus gustos, preferencias de lectura, "
            "géneros favoritos o libros similares que haya leído o mencionado. "
            "Se usa cuando el usuario busca sugerencias personalizadas y no un libro concreto."
        ),
        "examples": [
            "recomiéndame un buen libro para leer",
            "qué libro debería leer ahora",
            "me gusta la fantasía, qué me recomiendas",
            "quiero algo parecido a Dune",
            "sugiere un libro interesante",
            "recomiéndame un libro popular",
            "no sé qué leer, dame una recomendación",
            "quiero un libro corto y entretenido",
            "qué libros son buenos para empezar a leer",
            "sorpréndeme con una buena recomendación",
            
            
            "Cuéntame un poco sobre la trama de esta obra",
            "¿De qué trata este volumen?",
            "¿Quién es el autor de este título?",
            "¿Qué precio tiene este ejemplar?",
            "Dame más detalles técnicos de este producto",
            "¿Qué me puedes decir sobre el argumento?",
            "¿De qué género es esta pieza?",
            "¿Qué información tienes sobre esta creación?",
            "¿Vale la pena? Dame la sinopsis",
            "Dame el resumen detallado",
            "Explícame de qué va la historia",
            "¿Cuál es la descripción de este artículo?"
        ],
    },
    {
        "name": "get_book_product_details",
        "description": (
            "Obtener información detallada de un libro específico, incluyendo su descripción, "
            "autor, precio, género, disponibilidad y características relevantes. "
            "Esta función se usa cuando el usuario menciona un libro concreto y quiere conocer "
            "más detalles antes de comprarlo."
        ),
        "examples": [
            "cuéntame sobre el libro 1984",
            "de qué trata Dune",
            "quién es el autor de El Hobbit",
            "cuál es el precio de Clean Code",
            "dame detalles de este libro",
            "quiero saber más sobre este libro",
            "qué información tienes sobre este libro",
            "este libro de qué trata",
            "vale la pena este libro",
            "qué género es este libro",
            
            
            "Cuéntame un poco sobre la trama de esta obra",
            "¿De qué trata este volumen?",
            "¿Quién es el autor de este título?",
            "¿Qué precio tiene este ejemplar?",
            "Dame más detalles técnicos de este producto",
            "¿Qué me puedes decir sobre el argumento?",
            "¿De qué género es esta pieza?",
            "¿Qué información tienes sobre esta creación?",
            "¿Vale la pena? Dame la sinopsis",
            "Dame el resumen detallado",
            "Explícame de qué va la historia",
            "¿Cuál es la descripción de este artículo?"
            
        ],
    },
    {
        "name": "check_book_stock",
        "description": (
            "Consultar si un libro específico se encuentra disponible en la tienda y cuántas "
            "unidades hay en stock. Se utiliza cuando el usuario quiere asegurarse de que el "
            "libro está disponible antes de comprarlo."
        ),
        "examples": [
            "este libro está disponible",
            "tienen en stock Dune",
            "hay copias disponibles de El Hobbit",
            "cuántos libros de 1984 quedan",
            "aún tienen este libro",
            "queda algún ejemplar",
            "está agotado este libro",
            "puedo comprar este libro ahora",
            "hay disponibilidad de este título",
            "me confirmas si hay stock",
            
            
            "¿Tienen ejemplares de este en particular?",
            "¿Hay stock disponible para este título?",
            "¿Cuántas copias quedan en la tienda?",
            "¿Todavía lo tienen o ya se agotó?",
            "Confírmame si hay unidades físicas",
            "¿Queda algún ejemplar disponible?",
            "Dime si este está para entrega inmediata",
            "¿Tienen disponibilidad de esta obra?",
            "¿Cuántas unidades hay en almacén?",
            "¿Está agotado este producto?",
            "¿Puedo comprar esto ahora mismo?"
        ],
    },
    {
        "name": "add_book_to_cart",
        "description": (
            "Agregar uno o varios libros al carrito de compras del usuario. "
            "Se utiliza cuando el usuario expresa intención clara de compra, "
            "ya sea directa o implícita, y puede incluir una cantidad específica."
        ),
        "examples": [
            "agrega este libro al carrito",
            "quiero comprar este libro",
            "pon Dune en mi carrito",
            "agrega dos copias de 1984 al carrito",
            "añadir al carrito",
            "me llevo este libro",
            "quiero comprarlo",
            "guardar este libro en mi carrito",
            "agrega un ejemplar al carrito",
            "sumar este libro a mi compra",
            
            
            
            "Pon este en mi carrito",
            "Quiero comprar este, agrégalo",
            "Añade estas copias a mi compra",
            "Me llevo este ejemplar, mételo a la cesta",
            "Suma este a mi carrito",
            "Guárdame este para comprarlo",
            "Incluye este título en mi pedido",
            "Pon una unidad de este en mi selección",
            "Agrégalo a la bolsa de compras",
            "Me interesa adquirir este de aquí"
            
            
        ],
    },
    {
        "name": "remove_book_from_cart",
        "description": (
            "Eliminar un libro previamente agregado al carrito de compras. "
            "Se usa cuando el usuario ya no desea comprar un libro o quiere modificar su carrito."
        ),
        "examples": [
            "quita este libro del carrito",
            "elimina Dune de mi carrito",
            "ya no quiero este libro",
            "borra este libro del carrito",
            "remueve el libro del carrito",
            "saca este libro de mi compra",
            "cancelar este libro del carrito",
            "no quiero llevarme este libro",
            "eliminar este producto",
            "quitar libro del carrito",
            
            
            "Quita este de mi carrito",
            "Ya no quiero este, elimínalo",
            "Borra este de mi lista de compra",
            "Remueve este producto de mi selección",
            "Saca este de mi pedido",
            "Cancela este ítem de mi carrito",
            "Me arrepentí, quita este de la lista",
            "Elimina la última unidad que puse",
            "Limpia el carrito de este elemento",
            "No voy a llevar este al final"
        ],
    },
    {
        "name": "checkout_order",
        "description": (
            "Iniciar el proceso de compra a partir del carrito actual del usuario, "
            "creando una orden de compra. Se utiliza cuando el usuario expresa intención "
            "de finalizar la compra o proceder al pago."
        ),
        "examples": [
            "quiero pagar",
            "finalizar compra",
            "proceder al pago",
            "hacer el checkout",
            "terminar mi compra",
            "confirmar mi pedido",
            "realizar la orden",
            "quiero completar la compra",
            "cerrar el carrito y pagar",
            "hacer el pedido",
            
            
            "Ya quiero pagar todo",
            "Finalizar mi compra ahora",
            "Proceder al checkout",
            "Ir a la caja",
            "Terminar mi pedido",
            "Confirmar la orden de compra",
            "Quiero completar la transacción",
            "Cerrar el carrito y realizar el pedido",
            "Generar la orden con lo que tengo",
            "Listo para el pago final"
        ],
    },
    {
        "name": "process_payment",
        "description": (
            "Procesar el pago de una orden existente. "
            "En este proyecto académico, el pago es simulado y puede resultar "
            "aprobado o rechazado. Se utiliza cuando el usuario confirma el pago."
        ),
        "examples": [
            "pagar mi pedido",
            "realizar el pago",
            "pagar la orden",
            "confirmar el pago",
            "procesar pago",
            "ya quiero pagar",
            "pagar ahora",
            "hacer el pago de mi compra",
            "completar el pago",
            "autorizar el pago",
            
            
            
            "Efectuar el pago del pedido",
            "Pagar la orden ahora",
            "Confirmar que quiero realizar el pago",
            "Procesar la transacción",
            "Realizar el abono de la compra",
            "Autorizar el pago de mi cuenta",
            "Completar la transacción financiera",
            "Hacer el pago de lo pendiente",
            "Pagar el total de mi deuda",
            "Finalizar el proceso de cobro"
        ],
    },
    {
        "name": "cancel_order",
        "description": (
            "Cancelar una orden de compra que aún no ha sido pagada. "
            "Se utiliza cuando el usuario decide no continuar con la compra "
            "y desea anular su pedido."
        ),
        "examples": [
            "cancelar mi pedido",
            "no quiero esta orden",
            "anular la compra",
            "cancelar la orden",
            "ya no quiero comprar",
            "eliminar mi pedido",
            "cancelar el último pedido",
            "detener la compra",
            "quiero anular la orden",
            "cancelar pedido pendiente",
            
            
            "Cancela mi último pedido",
            "Ya no voy a comprar nada, anula la orden",
            "Quiero cancelar la compra pendiente",
            "Elimina mi orden actual",
            "Detén el proceso de este pedido",
            "Anular mi solicitud",
            "No proceses esto, cancélalo",
            "Descartar la orden generada",
            "Ya no quiero el pedido que hice",
            "Anulación total de mi compra activa"
            
        ],
    },
    {
        "name": "confirm_payment",
        "description": (
            "Confirmar y ejecutar el pago de una orden después de que el usuario haya "
            "revisado el monto y aceptado explícitamente. Se utiliza cuando el usuario "
            "responde afirmativamente a la pregunta de confirmación de pago."
        ),
        "examples": [
            "sí, confirmo el pago",
            "sí pagar",
            "confirmo",
            "dale",
            "sí, adelante",
            "ok, paga",
            "claro, procede",
            "sí quiero pagar",
            "confirmar pago",
            "va, págalo",
            "listo, confirmo",
            "seguro, pagar",
            "adelante con el pago",
            "procede con el pago",
            "sí, confirmo",
            "okey, pagar",
            "de acuerdo, paga",
            "sí, pagar ahora",
            "confirmo el pago de mi orden",
            "dale, paga la orden",
        ],
    },
    {
        "name": "view_cart",
        "description": (
            "Ver el contenido actual del carrito de compras del usuario, incluyendo "
            "los libros agregados, cantidades y el total. Se usa cuando el usuario "
            "quiere revisar qué tiene en su carrito antes de hacer checkout."
        ),
        "examples": [
            "ver mi carrito",
            "qué tengo en el carrito",
            "muéstrame mi carrito",
            "contenido del carrito",
            "mi carrito",
            "qué hay en mi carrito",
            "revisar carrito",
            "ver carrito de compras",
            "qué llevo en el carrito",
            "mostrar mi carrito",
            "dame mi carrito",
            "consultar carrito",
            "enseñame el carrito",
            "ver lo que tengo en el carrito",
            "qué productos tengo",
            "ver mi lista de compras",
        ],
    },
    {
        "name": "get_order_status",
        "description": (
            "Consultar el estado actual de una orden, incluyendo si está creada, "
            "pagada o cancelada. Se utiliza cuando el usuario quiere saber "
            "en qué estado se encuentra su pedido."
        ),
        "examples": [
            "cuál es el estado de mi pedido",
            "cómo va mi orden",
            "revisar mi pedido",
            "ver estado de la orden",
            "mi compra ya fue pagada",
            "el pedido sigue activo",
            "qué pasó con mi pedido",
            "estado de mi compra",
            "mi orden está confirmada",
            "consultar pedido",
            
            "¿Cómo va el estado de mi pedido?",
            "Dime si mi orden ya fue procesada",
            "¿Qué pasó con mi compra?",
            "Verificar el estatus de mi orden",
            "¿Mi pago fue aprobado?",
            "Revisar si mi pedido sigue activo",
            "¿En qué situación está mi transacción?",
            "Consultar si ya salió mi envío",
            "¿Está confirmada mi última gestión?",
            "Dime el estado de mi compra"
            
        ],
    },
]



async def compute_embeddings(texts: list[str]) -> list[list[float]]:
    from app.ai.semantic import get_embedding_model
    model = get_embedding_model()
    embeddings = model.encode(texts, normalize_embeddings=True)
    return [emb.tolist() for emb in embeddings]


async def seed_database(session: AsyncSession):
    result = await session.execute(select(Book).limit(1))
    if result.scalar_one_or_none():
        logger.info(" Base de datos ya contiene datos, omitiendo seed")
        return

    logger.info(" Iniciando seed de la base de datos...")

    # Users
    import hashlib
    demo_hash = hashlib.sha256("demo123".encode()).hexdigest()
    default_user = User(name="Demo User", email="demo@bookstore.com", password_hash=demo_hash)
    session.add(default_user)
    await session.flush()  # get auto-generated id

    # Books (with generated cover images)
    for book_data in BOOKS_DATA:
        cover = _generate_book_cover_base64(
            book_data["title"], book_data["author"], book_data.get("genre", "Fiction"),
        )
        session.add(Book(**book_data, image_base64=cover))

    # Semantic functions with embeddings (combined + individual multi-vector)
    logger.info(" Calculando embeddings para funciones semánticas...")

    # 1) Combined embeddings (backward-compatible)
    combined_texts = []
    for fn in SEMANTIC_FUNCTIONS:
        combined = f"{fn['description']} {' '.join(fn['examples'])}"
        combined_texts.append(combined)
    combined_embeddings = await compute_embeddings(combined_texts)

    # 2) Individual texts: 1 description + N examples per function
    individual_texts = []
    individual_meta = []  # (fn_index, embedding_type, text)
    for i, fn in enumerate(SEMANTIC_FUNCTIONS):
        individual_texts.append(fn["description"])
        individual_meta.append((i, "description", fn["description"]))
        for ex in fn["examples"]:
            individual_texts.append(ex)
            individual_meta.append((i, "example", ex))

    individual_embeddings = await compute_embeddings(individual_texts)

    # Create SemanticFunction rows
    sf_objects = []
    for fn_data, combined_emb in zip(SEMANTIC_FUNCTIONS, combined_embeddings):
        sf = SemanticFunction(
            name=fn_data["name"],
            description=fn_data["description"],
            examples=fn_data["examples"],
            embedding=combined_emb,
        )
        session.add(sf)
        sf_objects.append(sf)

    await session.flush()  # get auto-generated IDs

    # Create individual SemanticFunctionEmbedding rows
    total_individual = 0
    for (fn_idx, emb_type, text), emb_vec in zip(individual_meta, individual_embeddings):
        sfe = SemanticFunctionEmbedding(
            function_id=sf_objects[fn_idx].id,
            text=text,
            embedding_type=emb_type,
            embedding=emb_vec,
        )
        session.add(sfe)
        total_individual += 1

    await session.commit()
    logger.info(
        " Seed completado: %d libros, %d funciones semánticas, %d embeddings individuales",
        len(BOOKS_DATA), len(SEMANTIC_FUNCTIONS), total_individual,
    )
