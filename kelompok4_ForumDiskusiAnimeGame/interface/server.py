
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import json
import urllib.parse
import sys
import re
import traceback


# ==========================================
# PATH
# ==========================================

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent

CORPUS_PATH = ROOT / "data" / "processed" / "korpus_preprocessed.json"
INDEX_PATH = ROOT / "index_lucene"

HOST, PORT = "127.0.0.1", 8000

sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "preprocessing"))
sys.path.insert(0, str(ROOT / "lucene"))


# ==========================================
# IMPORT MODULE
# ==========================================

from preprocessing import preprocess_text

from lucene_engine import (
    daftar_konfigurasi,
    bangun_indeks
)


# ==========================================
# QUERY EXPANSION
# Diadaptasi dari notebook 05_query_expansion
# ==========================================

SYNONYM_GROUPS = [
    ("anime", "japanese animation"),
    ("manga", "japanese comic"),
    ("manhwa", "korean comic"),
    ("manhua", "chinese comic"),
    ("waifu", "favorite female character"),
    ("husbando", "favorite male character"),
    ("sub", "subtitles"),
    ("dub", "dubbing"),
    ("ova", "original video animation"),
    ("ost", "original soundtrack"),
    ("op", "opening song"),
    ("ed", "ending song"),
    ("isekai", "another world fantasy"),
    ("shonen", "boys manga"),
    ("rpg", "role playing game"),
    ("mmorpg", "massively multiplayer online role playing game"),
    ("fps", "first person shooter"),
    ("npc", "non player character"),
    ("pvp", "player versus player"),
    ("pve", "player versus environment"),
    ("dlc", "downloadable content"),
    ("bug", "glitch"),
    ("lag", "latency"),
    ("nerf", "weaken"),
    ("buff", "strengthen"),
    ("walkthrough", "strategy guide"),
    ("gacha", "random character draw"),
    ("guild", "clan")
]


def build_dictionary():
    dictionary = {}

    for left, right in SYNONYM_GROUPS:
        dictionary.setdefault(left.casefold(), set()).add(right.casefold())
        dictionary.setdefault(right.casefold(), set()).add(left.casefold())

    return dictionary


SYNONYM_DICTIONARY = build_dictionary()


def expand_query(query: str, max_expansions: int = 10) -> str:
    original = str(query).strip()

    if not original:
        return original

    lowered = original.casefold()
    additions = []

    for term in sorted(SYNONYM_DICTIONARY, key=len, reverse=True):
        pattern = (
            r"(?<![a-z0-9])"
            + re.escape(term)
            + r"(?![a-z0-9])"
        )

        if re.search(pattern, lowered):
            for alternative in sorted(SYNONYM_DICTIONARY[term]):

                if alternative not in lowered and alternative not in additions:
                    additions.append(alternative)

                    if len(additions) >= max_expansions:
                        break

        if len(additions) >= max_expansions:
            break

    if not additions:
        return original

    return original + " " + " ".join(additions)


def expand_and_preprocess_query(query: str) -> str:
    return preprocess_text(expand_query(query))


# ==========================================
# GLOBAL DATA
# ==========================================

DOKUMEN = []
INDEKS = {}

STATUS = {
    "ready": False,
    "message": "Indeks belum disiapkan."
}


# ==========================================
# LOAD CORPUS
# ==========================================

def muat_korpus():

    global DOKUMEN

    with CORPUS_PATH.open("r", encoding="utf-8") as f:
        data = json.load(f)

    if isinstance(data, list):
        DOKUMEN = data

    elif isinstance(data, dict):
        DOKUMEN = data.get(
            "documents",
            data.get("data", [])
        )

    else:
        raise ValueError("Format korpus tidak valid.")

    if not isinstance(DOKUMEN, list) or not DOKUMEN:
        raise ValueError("Korpus kosong atau format dokumen tidak valid.")

    for i, dok in enumerate(DOKUMEN):

        if not isinstance(dok, dict):
            raise ValueError(
                f"Dokumen ke-{i} bukan dictionary."
            )

        if "text_processed" not in dok:
            raise ValueError(
                f"Dokumen ke-{i} tidak memiliki text_processed."
            )

    print("Jumlah dokumen:", len(DOKUMEN))


# ==========================================
# BUILD INDEX
# ==========================================

def siapkan_indeks():

    global INDEKS

    konfigurasi = daftar_konfigurasi(preprocess_text)

    for kode, konfig in konfigurasi.items():

        print(f"\nMembangun indeks {kode}...")

        INDEKS[kode] = bangun_indeks(
            konfig,
            DOKUMEN,
            folder_dasar=str(INDEX_PATH)
        )

        print(f"Indeks {kode} berhasil dibuat.")
        print(INDEKS[kode].statistik())


# ==========================================
# SEARCH
# ==========================================

def cari_dokumen(
    query,
    model="M1",
    limit=10,
    expansion=False,
    sumber=None
):

    query = str(query).strip()
    model = str(model).upper()

    if model not in INDEKS:
        raise ValueError("Model pencarian tidak tersedia.")

    if not query:
        return {
            "query": query,
            "model": model,
            "total": 0,
            "hasil": [],
            "results": []
        }

    idx = INDEKS[model]

    query_diproses = None

    # --------------------------------------
    # QUERY EXPANSION
    # --------------------------------------

    if expansion:

        if model in ("M1", "M2"):
            query_diproses = expand_and_preprocess_query(query)

        elif model == "B1":
            query_diproses = expand_query(query)

    # --------------------------------------
    # PENCARIAN LUCENE
    # --------------------------------------

    hasil = idx.cari(
        query,
        k=len(DOKUMEN),
        query_diproses=query_diproses
    )

    # --------------------------------------
    # FILTER SUMBER
    # --------------------------------------

    if sumber and str(sumber).strip().lower() not in ("all", "semua"):

        sumber_filter = str(sumber).strip().casefold()

        hasil = [
            item for item in hasil
            if str(item.get("sumber") or "").casefold()
            == sumber_filter
        ]

    # Jumlah hasil sebelum diterapkan limit
    total_hasil = len(hasil)

    # --------------------------------------
    # LIMIT HASIL
    # --------------------------------------

    hasil = hasil[:limit]

    # --------------------------------------
    # MENAMBAHKAN CUPLIKAN
    # --------------------------------------

    for rank, item in enumerate(hasil, start=1):

        doc_id = item.get("doc_id")

        cuplikan = ""

        if isinstance(doc_id, int) and 0 <= doc_id < len(DOKUMEN):

            dok = DOKUMEN[doc_id]

            isi = (
                dok.get("content")
                or dok.get("body")
                or dok.get("text")
                or dok.get("text_processed")
                or ""
            )

            cuplikan = re.sub(
                r"\s+",
                " ",
                str(isi)
            ).strip()[:350]

        # Mempertahankan nama properti Lucene
        item["rank"] = rank
        item["cuplikan"] = cuplikan

        # Menyesuaikan nama properti dengan script.js
        item["snippet"] = cuplikan

    # --------------------------------------
    # RESPONSE
    # --------------------------------------

    query_expanded = (
        expand_query(query)
        if expansion
        else None
    )

    return {
        "query": query,
        "query_expansion": query_expanded,
        "query_diproses": query_diproses,
        "model": model,
        "total": total_hasil,

        # Format hasil asli
        "hasil": hasil,

        # Format yang dibaca oleh script.js
        "results": hasil
    }


# ==========================================
# HTTP HANDLER
# ==========================================

class Handler(BaseHTTPRequestHandler):

    def kirim_json(self, data, status=200):

        payload = json.dumps(
            data,
            ensure_ascii=False
        ).encode("utf-8")

        self.send_response(status)

        self.send_header(
            "Content-Type",
            "application/json; charset=utf-8"
        )

        self.send_header(
            "Content-Length",
            str(len(payload))
        )

        self.end_headers()
        self.wfile.write(payload)

    # --------------------------------------
    # GET
    # --------------------------------------

    def do_GET(self):

        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path

        # API CORPUS
        if path == "/api/corpus":

            try:
                self.kirim_json(DOKUMEN)

            except Exception as e:
                self.kirim_json(
                    {"error": str(e)},
                    500
                )

            return

        # API STATUS
        if path == "/api/status":

            self.kirim_json({
                **STATUS,
                "jumlah_dokumen": len(DOKUMEN),
                "model": list(INDEKS.keys()),

                "statistik": {
                    kode: idx.statistik()
                    for kode, idx in INDEKS.items()
                } if STATUS["ready"] else {}
            })

            return

        # ----------------------------------
        # STATIC FILE
        # ----------------------------------

        if path in ("/", "/index.html"):
            path = "/index.html"

        target = (
            HERE / path.lstrip("/")
        ).resolve()

        # Mencegah akses file di luar interface
        if HERE not in target.parents and target != HERE:
            self.send_error(403)
            return

        if not target.is_file():
            self.send_error(404)
            return

        data = target.read_bytes()

        content_type = {
            ".html": "text/html; charset=utf-8",
            ".css": "text/css; charset=utf-8",
            ".js": "application/javascript; charset=utf-8"
        }.get(
            target.suffix.lower(),
            "application/octet-stream"
        )

        self.send_response(200)

        self.send_header(
            "Content-Type",
            content_type
        )

        self.send_header(
            "Content-Length",
            str(len(data))
        )

        self.end_headers()
        self.wfile.write(data)

    # --------------------------------------
    # POST SEARCH
    # --------------------------------------

    def do_POST(self):

        parsed = urllib.parse.urlparse(self.path)

        if parsed.path != "/api/search":
            self.send_error(404)
            return

        try:

            panjang = int(
                self.headers.get("Content-Length", 0)
            )

            if panjang <= 0:
                raise ValueError("Request body kosong.")

            if panjang > 1_000_000:
                raise ValueError("Ukuran request terlalu besar.")

            body = self.rfile.read(panjang)

            data = json.loads(
                body.decode("utf-8")
            )

            if not isinstance(data, dict):
                raise ValueError("Format request tidak valid.")

            # ----------------------------------
            # REQUEST PARAMETERS
            # ----------------------------------

            query = data.get("query", "")
            model = data.get("model", "M1")

            limit = int(
                data.get("limit", 10)
            )

            expansion = data.get(
                "expansion",
                data.get("query_expansion", False)
            )

            sumber = data.get(
                "source",
                data.get("sumber")
            )

            # ----------------------------------
            # VALIDATION
            # ----------------------------------

            if not isinstance(query, str):
                raise ValueError("Query harus berupa teks.")

            if limit < 1 or limit > 100:
                raise ValueError(
                    "Limit harus antara 1 sampai 100."
                )

            if not isinstance(expansion, bool):
                raise ValueError(
                    "Query expansion harus berupa boolean."
                )

            # ----------------------------------
            # EXECUTE SEARCH
            # ----------------------------------

            hasil = cari_dokumen(
                query=query,
                model=model,
                limit=limit,
                expansion=expansion,
                sumber=sumber
            )

            self.kirim_json(hasil)

        except (ValueError, TypeError, json.JSONDecodeError) as e:

            self.kirim_json({
                "error": str(e)
            }, 400)

        except Exception as e:

            traceback.print_exc()

            self.kirim_json({
                "error": str(e)
            }, 500)


# ==========================================
# START SERVER
# ==========================================

if __name__ == "__main__":

    try:

        print("=" * 50)
        print("FORUMVERSE - SEARCH ENGINE")
        print("=" * 50)

        # ----------------------------------
        # CHECK CORPUS
        # ----------------------------------

        if not CORPUS_PATH.exists():

            raise FileNotFoundError(
                f"Korpus tidak ditemukan: {CORPUS_PATH}"
            )

        # ----------------------------------
        # LOAD CORPUS
        # ----------------------------------

        print("\nMemuat korpus...")
        muat_korpus()

        # ----------------------------------
        # BUILD INDEX
        # ----------------------------------

        print("\nMenyiapkan indeks Lucene...")
        siapkan_indeks()

        # ----------------------------------
        # UPDATE STATUS
        # ----------------------------------

        STATUS["ready"] = True

        STATUS["message"] = (
            "Semua model pencarian siap digunakan."
        )

        # ----------------------------------
        # START SERVER
        # ----------------------------------

        server = ThreadingHTTPServer(
            (HOST, PORT),
            Handler
        )

        print("\n" + "=" * 50)
        print("Semua indeks berhasil disiapkan.")
        print(f"Forumverse: http://localhost:{PORT}")
        print(f"Corpus: {CORPUS_PATH}")
        print("Model tersedia:", ", ".join(INDEKS.keys()))
        print("=" * 50)

        server.serve_forever()

    except KeyboardInterrupt:

        print("\nServer dihentikan.")

    except Exception as e:

        STATUS["ready"] = False
        STATUS["message"] = str(e)

        print("\nERROR:", e)
        traceback.print_exc()
