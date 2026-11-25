"""
Tiga konfigurasi (kelas similarity yang berbeda + baseline):

    M1  BM25Similarity      + WhitespaceAnalyzer pada token hasil preprocessing
    M2  ClassicSimilarity   + WhitespaceAnalyzer pada token hasil preprocessing
        (TF-IDF klasik Lucene)
    B1  BM25Similarity      + StandardAnalyzer pada teks mentah (BASELINE)

Preprocessing memakai SATU fungsi yang sama untuk dokumen dan query
(`preprocessing.preprocess_text`). Token hasil preprocessing diindeks dengan
WhitespaceAnalyzer, sehingga Lucene tidak mengubah token lagi.
"""
from __future__ import annotations

import math
import os
import shutil
from pathlib import Path

# PyLucene dibangun terhadap JDK 21; arahkan JAVA_HOME ke sana (Colab/Ubuntu) sebelum JVM dijalankan.
for _jh in ("/usr/lib/jvm/java-21-openjdk-amd64", "/usr/lib/jvm/java-21-openjdk"):
    if os.path.isdir(_jh):
        os.environ["JAVA_HOME"] = _jh
        os.environ["PATH"] = _jh + "/bin:" + os.environ["PATH"]
        break

import lucene

try:                                    # JVM hanya boleh dijalankan sekali per proses
    _vm = lucene.getVMEnv()
except Exception:
    _vm = None
if _vm is None:
    lucene.initVM(vmargs=["-Djava.awt.headless=true"])

from java.nio.file import Paths
from org.apache.lucene.analysis.core import WhitespaceAnalyzer
from org.apache.lucene.analysis.standard import StandardAnalyzer
from org.apache.lucene.analysis.tokenattributes import CharTermAttribute
from org.apache.lucene.document import Document, Field, FieldType, StoredField, TextField
from org.apache.lucene.index import (DirectoryReader, IndexWriter, IndexWriterConfig,
                                     MultiTerms, PostingsEnum, Term)
from org.apache.lucene.queryparser.classic import QueryParser
from org.apache.lucene.search import (BooleanClause, BooleanQuery, BoostQuery,
                                      IndexSearcher, TermQuery)
from org.apache.lucene.search.similarities import BM25Similarity, ClassicSimilarity
from org.apache.lucene.store import FSDirectory
from org.apache.lucene.util import BytesRef

FIELD = "isi"                    # satu-satunya field teks yang dicari
NO_MORE_DOCS = 2147483647        # DocIdSetIterator.NO_MORE_DOCS
BM25_K1, BM25_B = 1.2, 0.75      # nilai bawaan Lucene, ditulis eksplisit


def _iter_term(te):
    """Iterasi semua term pada sebuah TermsEnum (menghasilkan BytesRef).

    `next()` dideklarasikan di tipe induk `BytesRefIterator`. Pada PyLucene 10 (JCC) metode itu
    tidak muncul di objek `TermsEnum`, sehingga objek harus di-cast ke `BytesRefIterator` dulu.
    Posisi enum Java tetap sama, jadi `te.totalTermFreq()` dst. tetap bisa dipakai di dalam loop.
    """
    if hasattr(te, "next"):                              # Lucene/pembungkus yang menampilkan next()
        while True:
            b = te.next()
            if b is None:
                return
            yield b
        return
    try:
        from org.apache.lucene.util import BytesRefIterator
        it = BytesRefIterator.cast_(te)
    except Exception as e:
        raise RuntimeError("Tidak bisa meng-cast TermsEnum ke BytesRefIterator: %r. Metode TermsEnum: %s"
                           % (e, [m for m in dir(te) if not m.startswith("_")]))
    if hasattr(it, "next"):
        while True:
            b = it.next()
            if b is None:
                return
            yield b
    else:                                                # JCC dapat menjadikan next() protokol iterator Python
        try:
            for b in it:
                yield b
        except TypeError:
            raise RuntimeError("BytesRefIterator tidak punya next() dan tidak bisa diiterasi. Metode: %s"
                               % [m for m in dir(it) if not m.startswith("_")])


def token_analyzer(analyzer, teks):
    """Daftar token yang dihasilkan sebuah analyzer Lucene untuk `teks`."""
    ts = analyzer.tokenStream(FIELD, teks)
    atribut = ts.addAttribute(CharTermAttribute.class_)
    ts.reset()
    hasil = []
    while ts.incrementToken():
        hasil.append(atribut.toString())
    ts.end()
    ts.close()
    return hasil


def _tipe_field_isi():
    """Field teks tanpa disimpan, dengan term vector (dibutuhkan Rocchio)."""
    tipe = FieldType(TextField.TYPE_NOT_STORED)
    tipe.setStoreTermVectors(True)
    return tipe


def teks_custom(dok):
    """Teks yang diindeks pada konfigurasi custom: hasil preprocessing korpus."""
    return dok["text_processed"]


def teks_mentah(dok):
    """Teks yang diindeks pada baseline: judul + isi asli, tanpa preprocessing."""
    return (dok.get("title") or "") + ". " + (dok.get("content") or "")


class Konfigurasi:
    def __init__(self, kode, nama, model, analisis, buat_analyzer, buat_similarity,
                 ambil_teks, prepro_query):
        self.kode = kode
        self.nama = nama
        self.model = model                      # nama model retrieval
        self.analisis = analisis                # nama analyzer (untuk tabel)
        self.buat_analyzer = buat_analyzer
        self.buat_similarity = buat_similarity
        self.ambil_teks = ambil_teks            # dokumen -> teks yang diindeks
        self.prepro_query = prepro_query        # query mentah -> teks query


def daftar_konfigurasi(preprocess_text):
    """Tiga konfigurasi UAS. `preprocess_text` = fungsi dari preprocessing.py."""
    return {
        "M1": Konfigurasi("M1", "BM25 + custom preprocessing", "BM25Similarity",
                          "WhitespaceAnalyzer (token hasil preprocess_text)",
                          WhitespaceAnalyzer,
                          lambda: BM25Similarity(BM25_K1, BM25_B),
                          teks_custom, preprocess_text),
        "M2": Konfigurasi("M2", "TF-IDF (ClassicSimilarity) + custom preprocessing",
                          "ClassicSimilarity",
                          "WhitespaceAnalyzer (token hasil preprocess_text)",
                          WhitespaceAnalyzer, ClassicSimilarity,
                          teks_custom, preprocess_text),
        "B1": Konfigurasi("B1", "BM25 + StandardAnalyzer (baseline)", "BM25Similarity",
                          "StandardAnalyzer (teks mentah)",
                          StandardAnalyzer,
                          lambda: BM25Similarity(BM25_K1, BM25_B),
                          teks_mentah, lambda q: q),
    }


def _dokumen_tersimpan(searcher, doc_id):
    try:                                        # Lucene 9.5+
        return searcher.storedFields().document(doc_id)
    except AttributeError:
        return searcher.doc(doc_id)


class Indeks:
    """Satu indeks Lucene (satu konfigurasi) beserta searcher-nya."""

    def __init__(self, konfig, folder, reader, searcher, analyzer, similarity):
        self.konfig = konfig
        self.folder = folder
        self.reader = reader
        self.searcher = searcher
        self.analyzer = analyzer
        self.similarity = similarity

    # statistik
    def statistik(self):
        n_term = MultiTerms.getTerms(self.reader, FIELD).size()
        if n_term < 0:                          # jumlah term tidak diketahui -> hitung
            n_term = sum(1 for _ in _iter_term(MultiTerms.getTerms(self.reader, FIELD).iterator()))
        total = self.reader.getSumTotalTermFreq(FIELD)
        n_dok = self.reader.getDocCount(FIELD)
        return {"dokumen": self.reader.numDocs(), "term_unik": int(n_term),
                "total_token": int(total), "rata2_token_per_dok": round(total / max(n_dok, 1), 1)}

    # pencarian
    def _query(self, teks):
        return QueryParser(FIELD, self.analyzer).parse(QueryParser.escape(teks))

    def teks_query(self, query, query_diproses=None):
        """Teks query yang benar-benar dikirim ke Lucene.

        `query_diproses`: isi bila query SUDAH dipreprocess (misal keluaran
        query expansion); dipakai apa adanya agar preprocessing tidak dua kali.
        """
        return query_diproses if query_diproses is not None else self.konfig.prepro_query(query)

    def cari(self, query, k=10, query_diproses=None):
        """[{rank, doc_id, judul, url, sumber, skor}] terurut menurut skor model."""
        teks = self.teks_query(query, query_diproses)
        if not teks.strip():
            return []
        return self._hasil(self.searcher.search(self._query(teks), k))

    def cari_berbobot(self, bobot_term, k=10, maks_term=200):
        """Query berbobot {term: bobot}; term harus sudah dalam bentuk token indeks.

        Dipakai Rocchio: vektor query baru (term -> bobot) dijalankan sebagai
        BooleanQuery dari TermQuery yang dibungkus BoostQuery.
        """
        urut = sorted(((t, w) for t, w in bobot_term.items() if w > 0),
                      key=lambda x: -x[1])[:maks_term]
        if not urut:
            return []
        bq = BooleanQuery.Builder()                         # maks 1024 klausul; dibatasi `maks_term`
        for term, w in urut:
            bq.add(BoostQuery(TermQuery(Term(FIELD, term)), float(w)), BooleanClause.Occur.SHOULD)
        return self._hasil(self.searcher.search(bq.build(), k))

    def _hasil(self, top):
        hasil = []
        for rank, sd in enumerate(top.scoreDocs, start=1):
            d = _dokumen_tersimpan(self.searcher, sd.doc)
            hasil.append({"rank": rank, "doc_id": int(d.get("id")), "judul": d.get("judul"),
                          "url": d.get("url"), "sumber": d.get("sumber"),
                          "skor": float(sd.score)})
        return hasil

    # posting list, vektor
    def posting_list(self, term, maks=10, posisi=True):
        """Posting list satu term: df, total frekuensi, dan `maks` posting pertama.

        Tiap posting = (doc_id korpus, frekuensi term, posisi-posisi term).
        Mengembalikan None bila term tidak ada di indeks.
        """
        terms = MultiTerms.getTerms(self.reader, FIELD)
        te = terms.iterator()
        if not te.seekExact(BytesRef(term)):
            return None
        info = {"term": term, "df": int(te.docFreq()), "total_tf": int(te.totalTermFreq()),
                "posting": []}
        pe = te.postings(None, PostingsEnum.POSITIONS if posisi else PostingsEnum.FREQS)
        while len(info["posting"]) < maks:
            lid = pe.nextDoc()
            if lid == NO_MORE_DOCS:
                break
            freq = int(pe.freq())
            pos = [int(pe.nextPosition()) for _ in range(freq)] if posisi else []
            d = _dokumen_tersimpan(self.searcher, lid)
            info["posting"].append((int(d.get("id")), freq, pos))
        return info

    def term_vector(self, doc_id):
        """{term: tf} dari term vector satu dokumen (bahan Rocchio)."""
        try:                                    # Lucene 9.5+ / 10
            tv = self.reader.termVectors().get(doc_id, FIELD)
        except AttributeError:
            tv = self.reader.getTermVector(doc_id, FIELD)
        hasil = {}
        if tv is None:
            return hasil
        te = tv.iterator()
        for b in _iter_term(te):
            hasil[b.utf8ToString()] = int(te.totalTermFreq())
        return hasil

    def df(self, term):
        """Document frequency sebuah term di indeks ini."""
        return int(self.reader.docFreq(Term(FIELD, term)))

    # skor
    def jelaskan(self, query, doc_id, query_diproses=None):
        """Teks `Explanation` Lucene: rincian skor dokumen `doc_id` untuk query."""
        teks = self.teks_query(query, query_diproses)
        return self.searcher.explain(self._query(teks), doc_id).toString()

    def idf_manual(self, term):
        """IDF yang dihitung dengan rumus model, untuk dicocokkan dengan explain()."""
        n_dok = self.reader.getDocCount(FIELD)
        df = self.df(term)
        if self.konfig.model == "BM25Similarity":
            return math.log(1 + (n_dok - df + 0.5) / (df + 0.5))
        return math.log((n_dok + 1) / (df + 1)) + 1.0     # ClassicSimilarity

    def tutup(self):
        self.reader.close()


def bangun_indeks(konfig, dokumen, folder_dasar="index_lucene"):
    """Bangun indeks Lucene satu konfigurasi dari daftar dokumen korpus.

    Kesamaan similarity wajib: IndexWriterConfig.setSimilarity() saat indexing
    DAN IndexSearcher.setSimilarity() saat searching memakai model yang sama.
    """
    folder = Path(folder_dasar) / konfig.kode
    shutil.rmtree(folder, ignore_errors=True)
    folder.parent.mkdir(parents=True, exist_ok=True)

    analyzer = konfig.buat_analyzer()
    similarity = konfig.buat_similarity()
    direktori = FSDirectory.open(Paths.get(str(folder)))

    cfg = IndexWriterConfig(analyzer)
    cfg.setSimilarity(similarity)                           # model saat indexing
    cfg.setOpenMode(IndexWriterConfig.OpenMode.CREATE)
    writer = IndexWriter(direktori, cfg)
    tipe = _tipe_field_isi()
    for i, dok in enumerate(dokumen):
        d = Document()
        d.add(Field(FIELD, konfig.ambil_teks(dok), tipe))
        d.add(StoredField("id", str(i)))                    # id = urutan di korpus
        d.add(StoredField("judul", dok.get("title") or ""))
        d.add(StoredField("url", dok.get("url") or ""))
        d.add(StoredField("sumber", dok.get("source") or ""))
        writer.addDocument(d)
    writer.forceMerge(1)                                    # satu segmen -> docID = urutan korpus
    writer.commit()
    writer.close()

    reader = DirectoryReader.open(direktori)
    searcher = IndexSearcher(reader)
    searcher.setSimilarity(similarity)                      # model saat searching
    idx = Indeks(konfig, str(folder), reader, searcher, analyzer, similarity)
    for contoh in (0, len(dokumen) // 2, len(dokumen) - 1):  # docID Lucene == id korpus
        assert int(_dokumen_tersimpan(searcher, contoh).get("id")) == contoh
    return idx

# Alat bantu penilaian relevansi dan ekspor hasil (dipanggil dari notebook)

def _baca_csv(berkas):
    """Baca CSV penilaian; pemisah (koma atau titik koma dari Excel lokal Indonesia) dideteksi otomatis."""
    import pandas as pd
    return pd.read_csv(berkas, encoding="utf-8-sig", sep=None, engine="python", dtype=str).fillna("")


def buat_pool_penilaian(indeks, dokumen, queries, milikku, hasil_dir, kedalaman=10, seed=2026):
    """Buat berkas penilaian manual (pooling) untuk query `milikku`.

    Pool = gabungan top-`kedalaman` dari SEMUA konfigurasi (tanpa duplikat), ditulis dalam
    urutan acak dan tanpa skor/peringkat agar penilaian tidak bias terhadap model tertentu.
    Berkas yang sudah berisi penilaian dan query-nya sama TIDAK ditimpa.
    """
    import csv, random, re
    import pandas as pd
    hasil_dir = Path(hasil_dir)
    hasil_dir.mkdir(parents=True, exist_ok=True)
    nama = "penilaian_" + "_".join(milikku) + ".csv"
    berkas = hasil_dir / nama

    pool = {}
    for qid in milikku:
        for kode, idx in indeks.items():
            for r in idx.cari(queries[qid], kedalaman):
                pool.setdefault((qid, r["doc_id"]), {})[kode] = r["rank"]
    urut = list(pool)
    random.Random(seed).shuffle(urut)

    def tulis():
        with open(berkas, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.writer(f)
            w.writerow(["qid", "query", "doc_id", "judul", "sumber", "url", "isi_awal", "relevan"])
            for qid, doc_id in urut:
                d = dokumen[doc_id]
                isi = re.sub(r"\s+", " ", d["content"]).strip()[:600]
                w.writerow([qid, queries[qid], doc_id, d["title"], d["source"], d["url"], isi, ""])

    if berkas.exists():
        lama = _baca_csv(berkas)
        sudah_diisi = bool((lama["relevan"].str.strip() != "").any())
        query_sama = set(zip(lama["qid"], lama["query"])) == {(q, queries[q]) for q in milikku}
        if sudah_diisi and query_sama:
            print("PERHATIAN:", nama, "sudah berisi penilaian dan query-nya sama -> TIDAK ditimpa.")
        else:
            if sudah_diisi:
                cadangan = hasil_dir / (berkas.stem + "_LAMA_query_berbeda.csv")
                shutil.copy(berkas, cadangan)
                print("Query berubah: berkas lama dicadangkan ke", cadangan.name)
            tulis()
    else:
        tulis()

    # Peringkat tiap model disimpan terpisah
    pd.DataFrame([{"qid": q, "doc_id": d, **{k: pool[(q, d)].get(k) for k in indeks}} for q, d in pool]).to_csv(
        hasil_dir / ("pool_peringkat_" + "_".join(milikku) + "_JANGAN_DILIHAT.csv"), index=False, encoding="utf-8-sig")
    per_query = {}
    for q, _ in pool:
        per_query[q] = per_query.get(q, 0) + 1
    print("Dokumen yang harus dinilai:", per_query, "| total", len(pool))
    print("Berkas untuk diisi:", berkas)
    return berkas


def muat_penilaian(hasil_dir, milikku=("Q6", "Q7")):
    """Baca penilaian 0/1, validasi, dan simpan relevansi_<qid>.json. None bila belum lengkap."""
    import json
    hasil_dir = Path(hasil_dir)
    nama = "_".join(milikku)
    df = _baca_csv(hasil_dir / ("penilaian_" + nama + ".csv"))
    isi = df["relevan"].str.strip()
    kosong = isi == ""
    salah = ~isi.isin(["0", "1"]) & ~kosong
    if kosong.any() or salah.any():
        print("Belum lengkap: %d baris kosong, %d baris bukan 0/1. Lengkapi dulu." % (int(kosong.sum()), int(salah.sum())))
        return None
    df["relevan"] = isi.astype(int)
    df["doc_id"] = df["doc_id"].astype(int)
    rel = {q: sorted(g.loc[g["relevan"] == 1, "doc_id"].tolist()) for q, g in df.groupby("qid")}
    dinilai = {q: sorted(g["doc_id"].tolist()) for q, g in df.groupby("qid")}
    with open(hasil_dir / ("relevansi_" + nama + ".json"), "w") as f:
        json.dump({"relevan": rel, "dinilai": dinilai}, f, indent=1)
    print("Penilaian tersimpan. Jumlah dokumen relevan:", {q: len(v) for q, v in rel.items()},
          "| dinilai:", {q: len(v) for q, v in dinilai.items()})
    return rel


def ekspor_ranking(indeks, queries, hasil_dir, k=100):
    """Simpan peringkat top-k tiap query untuk tiap konfigurasi (bahan anggota evaluasi)."""
    import json
    hasil_dir = Path(hasil_dir)
    ranking = {kode: {qid: [[r["doc_id"], round(r["skor"], 5)] for r in idx.cari(q, k)]
                      for qid, q in queries.items()} for kode, idx in indeks.items()}
    berkas = hasil_dir / "ranking_semua_query.json"
    with open(berkas, "w") as f:
        json.dump({"queries": queries, "ranking": ranking}, f)
    print("Tersimpan:", berkas)
    return ranking


def kemas_hasil(hasil_dir, nama="hasil_lucene"):
    """Zip seluruh isi folder hasil; di Colab zip langsung diunduh ke komputer."""
    arsip = shutil.make_archive(nama, "zip", str(hasil_dir))
    print("Zip:", arsip, "| isi:", sorted(p.name for p in Path(hasil_dir).iterdir()))
    try:
        from google.colab import files
        files.download(arsip)
    except ImportError:
        pass
    return arsip
