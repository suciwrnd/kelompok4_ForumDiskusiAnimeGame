# Lucene (PyLucene) – cara pasang dan menjalankan

Bagian anggota 3: indexing Lucene, 2 model retrieval, baseline `StandardAnalyzer`, posting list.

Versi yang dipakai: **PyLucene 10.0.0** (Apache Lucene 10), **JDK 21**, Python 3.10+.
PyLucene **tidak ada di `pip`**; ia dikompilasi dari kode sumber. Prosesnya 10–20 menit, cukup sekali per sesi/mesin.

## Cara tercepat: Google Colab

1. Buka `lucene/06_lucene_indexing.ipynb` di Colab (Upload notebook, atau buka dari GitHub).
2. Jalankan sel **0. Memasang PyLucene** dan tunggu selesai (10–20 menit).
   Bila ada pesan *"belum terbaca"*: **Runtime → Restart session**, lalu **Run all** dari awal
   (sel pemasangan otomatis terlewati karena PyLucene sudah terpasang).
3. Jalankan sel berikutnya. Saat diminta, unggah `kelompok4_ForumDiskusiAnimeGame.zip`
   (zip proyek yang sudah berisi folder `lucene/`). Notebook mengekstraknya sendiri.

Catatan Colab:
- Bila runtime direset/terputus, hasil kompilasi hilang. Jalankan sel pemasangan lagi (10–20 menit).
- Pilih runtime CPU biasa; GPU tidak dibutuhkan.
- Folder `index_lucene/` hanya indeks kerja dan dibangun ulang dalam beberapa detik (4090 dokumen).

## Linux / Ubuntu / WSL2 (untuk demo lokal)

Windows dan macOS tidak didukung langsung; pada Windows pakai **WSL2 (Ubuntu)**.

```bash
sudo apt-get update
sudo apt-get install -y openjdk-21-jdk-headless ant build-essential python3-dev python3-venv curl
export JAVA_HOME=/usr/lib/jvm/java-21-openjdk-amd64
export PATH=$JAVA_HOME/bin:$PATH
# JCC mencari libjvm di jre/lib/amd64; pada JDK modern letaknya di lib/
sudo mkdir -p $JAVA_HOME/jre/lib && sudo ln -sfn ../../lib $JAVA_HOME/jre/lib/amd64

python3 -m venv ~/venv-pylucene && source ~/venv-pylucene/bin/activate
pip install setuptools wheel

mkdir -p ~/pylucene_src && cd ~/pylucene_src
curl -sSL https://archive.apache.org/dist/lucene/pylucene/pylucene-10.0.0-src.tar.gz | tar -xz --strip-components=1

(cd jcc && NO_SHARED=1 JCC_JDK=$JAVA_HOME pip install --no-build-isolation .)
NO_SHARED=1 JCC_JDK=$JAVA_HOME make all install JCC="python -m jcc" ANT=ant PYTHON=python NUM_FILES=8
```

Uji pemasangan:

```bash
python -c "import lucene; lucene.initVM(); print('PyLucene', lucene.VERSION)"
```

Bila `import lucene` gagal setelah `make install`, tambahkan egg hasil pemasangan ke `PYTHONPATH`
(`ls $VIRTUAL_ENV/lib/python3*/site-packages/*.egg`), atau restart shell.

## Menjalankan bagian ini

```bash
pip install -r requirements.txt        # pandas, nltk, dst. (PyLucene dipasang terpisah, lihat di atas)
jupyter notebook lucene/06_lucene_indexing.ipynb
```

Modul `lucene/lucene_engine.py` dipakai anggota lain:

```python
import sys; sys.path.insert(0, "preprocessing"); sys.path.insert(0, "lucene")
import json, lucene_engine as E
from preprocessing import preprocess_text

dokumen = json.load(open("data/processed/korpus_preprocessed.json", encoding="utf-8"))
konfig  = E.daftar_konfigurasi(preprocess_text)                    # M1 (BM25), M2 (TF-IDF), B1 (baseline)
indeks  = {k: E.bangun_indeks(c, dokumen, "index_lucene") for k, c in konfig.items()}

for r in indeks["M1"].cari("best RPG game", k=10):                 # query mentah -> dipreprocess otomatis
    print(r["rank"], r["skor"], r["judul"], r["url"])

# Query yang SUDAH dipreprocess (misal keluaran query expansion): jangan diproses dua kali
indeks["M1"].cari("rpg game", query_diproses="rpg game role play")

# Untuk Rocchio
tf = indeks["M1"].term_vector(3402)                                # {term: tf} dari term vector
indeks["M1"].cari_berbobot({"rpg": 2.0, "game": 1.0}, k=10)        # query berbobot {term: bobot}
```

Ringkasan antarmuka `Indeks`: `cari`, `cari_berbobot`, `posting_list`, `term_vector`, `df`, `statistik`,
`jelaskan` (explain Lucene), `idf_manual`.

## Pembagian bahan untuk anggota lain

| Anggota | Butuh PyLucene? | Cukup pakai |
|---|---|---|
| Evaluasi (Precision/Recall/F1/MAP) | Tidak | `lucene/hasil/ranking_semua_query.json` + penilaian relevansi semua anggota |
| Rocchio (term vector) | Ya | `lucene_engine.py` (`term_vector`, `cari_berbobot`) di Colab yang sudah terpasang |
| Antarmuka pencarian (demo) | Ya | `lucene_engine.py` pada mesin/Colab yang PyLucene-nya sudah terpasang |

## .gitignore yang disarankan

```
index_lucene/
lucene/hasil/pool_peringkat_Q6_Q7_JANGAN_DILIHAT.csv
```
