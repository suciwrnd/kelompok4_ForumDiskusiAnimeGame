
// ==========================================
// FORUMVERSE - SEARCH INTERFACE
// Connected to Python / Lucene Backend
// ==========================================

let corpus = [];

const searchForm = document.getElementById("searchForm");
const resultsContainer = document.getElementById("resultsContainer");
const searchStatus = document.getElementById("searchStatus");

const searchInput = document.getElementById("searchInput");
const searchButton = document.getElementById("searchButton");

const sourceFilter = document.getElementById("sourceFilter");
const modelSelect = document.getElementById("modelSelect");
const resultLimit = document.getElementById("resultLimit");
const expansionToggle = document.getElementById("expansionToggle");

const totalDocuments = document.getElementById("totalDocuments");


// ==========================================
// HELPER: HTML ESCAPE
// ==========================================

function escapeHTML(value) {
    return String(value ?? "").replace(
        /[&<>"']/g,
        character => {
            const entities = {
                "&": "&amp;",
                "<": "&lt;",
                ">": "&gt;",
                '"': "&quot;",
                "'": "&#39;"
            };

            return entities[character];
        }
    );
}


// ==========================================
// HELPER: CLEAN CONTENT
// ==========================================

function cleanContent(content) {
    return String(content ?? "")
        .replace(/<[^>]*>/g, " ")
        .replace(/&nbsp;/gi, " ")
        .replace(/&amp;/gi, "&")
        .replace(/&quot;/gi, '"')
        .replace(/&#39;/gi, "'")
        .replace(/\s+/g, " ")
        .trim();
}


// ==========================================
// HELPER: URL VALIDATION
// ==========================================

function safeURL(value) {
    try {
        const url = new URL(value);

        if (
            url.protocol === "http:" ||
            url.protocol === "https:"
        ) {
            return url.href;
        }
    } catch (error) {
        return "";
    }

    return "";
}


// ==========================================
// HELPER: SOURCE CLASS
// ==========================================

function getSourceClass(source) {
    const normalized = String(source ?? "").toLowerCase();

    if (normalized.includes("gaming")) {
        return "gaming";
    }

    if (normalized.includes("mal")) {
        return "mal";
    }

    if (normalized.includes("steam")) {
        return "steam";
    }

    if (normalized.includes("anilist")) {
        return "anilist";
    }

    if (normalized.includes("anime")) {
        return "";
    }

    return "";
}


// ==========================================
// LOAD CORPUS INFORMATION
// Used for document count and source filter
// ==========================================

async function loadCorpus() {
    try {
        const response = await fetch("/api/corpus");

        if (!response.ok) {
            throw new Error("Gagal mengambil informasi korpus.");
        }

        const data = await response.json();

        if (data.error) {
            throw new Error(data.error);
        }

        corpus = Array.isArray(data)
            ? data
            : (data.documents || []);

        // Update total document count if element exists
        if (totalDocuments) {
            totalDocuments.textContent =
                corpus.length.toLocaleString("id-ID");
        }

        populateSourceFilter();

        searchStatus.textContent =
            `Korpus siap digunakan (${corpus.length.toLocaleString("id-ID")} dokumen).`;

    } catch (error) {
        console.error("Corpus loading error:", error);

        // Search can still be attempted through /api/search.
        searchStatus.textContent =
            "Informasi korpus belum tersedia. Periksa koneksi backend.";
    }
}


// ==========================================
// POPULATE SOURCE FILTER
// ==========================================

function populateSourceFilter() {
    if (!sourceFilter) return;

    const sources = [
        ...new Set(
            corpus
                .map(doc => doc.source || doc.sumber)
                .filter(Boolean)
        )
    ].sort();

    sourceFilter.innerHTML =
        '<option value="">ALL SOURCES</option>';

    sources.forEach(source => {
        const option = document.createElement("option");

        option.value = source;
        option.textContent = source;

        sourceFilter.appendChild(option);
    });
}


// ==========================================
// SEARCH STATUS
// ==========================================

function setSearchLoading(isLoading) {
    if (searchButton) {
        searchButton.disabled = isLoading;

        searchButton.textContent = isLoading
            ? "SEARCHING..."
            : "SEARCH ↗";
    }

    if (searchInput) {
        searchInput.disabled = isLoading;
    }
}


// ==========================================
// DISPLAY EMPTY STATE
// ==========================================

function showEmptyResults(title, message) {
    resultsContainer.innerHTML = `
        <div class="empty-results">
            <h3>${escapeHTML(title)}</h3>
            <p>${escapeHTML(message)}</p>
        </div>
    `;
}


// ==========================================
// SEARCH USING PYTHON BACKEND
// ==========================================

async function performSearch() {
    const query = searchInput.value.trim();

    if (!query) {
        showEmptyResults(
            "Enter a keyword",
            "Start searching for a discussion."
        );

        searchStatus.textContent =
            "Masukkan kata kunci pencarian.";

        searchInput.focus();
        return;
    }

    // Get selected search settings
    const selectedModel = modelSelect
        ? modelSelect.value
        : "M1";

    const selectedLimit = resultLimit
        ? Number(resultLimit.value)
        : 10;

    const queryExpansion = expansionToggle
        ? expansionToggle.checked
        : true;

    const selectedSource = sourceFilter
        ? sourceFilter.value
        : "";

    // Request payload for Python backend
    const payload = {
        query: query,
        model: selectedModel,
        limit: selectedLimit,
        query_expansion: queryExpansion,
        source: selectedSource || null
    };

    try {
        setSearchLoading(true);

        searchStatus.textContent =
            "Searching discussions...";

        resultsContainer.innerHTML = `
            <div class="result-placeholder">
                <div class="placeholder-symbol">⌕</div>
                <h3>SEARCHING...</h3>
                <p>Finding relevant discussions from the corpus.</p>
            </div>
        `;

        // Send query to backend
        const response = await fetch("/api/search", {
            method: "POST",

            headers: {
                "Content-Type": "application/json"
            },

            body: JSON.stringify(payload)
        });

        if (!response.ok) {
            let errorMessage = "Search request failed.";

            try {
                const errorData = await response.json();

                if (errorData.error) {
                    errorMessage = errorData.error;
                }
            } catch (error) {
                // Keep default error message
            }

            throw new Error(errorMessage);
        }

        const data = await response.json();

        if (data.error) {
            throw new Error(data.error);
        }

        // Support either {results: []} or {documents: []}
        const results = Array.isArray(data)
            ? data
            : (data.results || data.documents || []);

        displayResults(results, data);

    } catch (error) {
        console.error("Search error:", error);

        searchStatus.textContent =
            "Pencarian gagal.";

        showEmptyResults(
            "Unable to search",
            error.message || "Terjadi kesalahan pada server."
        );

    } finally {
        setSearchLoading(false);
    }
}


// ==========================================
// DISPLAY SEARCH RESULTS
// ==========================================

function displayResults(results, responseData = {}) {
    if (!Array.isArray(results) || results.length === 0) {
        searchStatus.textContent =
            "Tidak ada diskusi yang cocok ditemukan.";

        showEmptyResults(
            "No discussions found.",
            "Try different keywords or another source."
        );

        return;
    }

    const model = responseData.model || modelSelect?.value || "M1";

    const total = responseData.total ?? results.length;

    searchStatus.textContent =
        `${total} results found · Model ${model}`;

    resultsContainer.innerHTML = results.map((item, index) => {
        // Support both Lucene result field names
        // and original corpus field names.
        const title = escapeHTML(
            item.judul || item.title || "Untitled document"
        );

        const source = String(
            item.sumber || item.source || "Unknown"
        );

        const sourceName = escapeHTML(source);
        const sourceClass = getSourceClass(source);

        const content = cleanContent(
            item.snippet ||
            item.content ||
            item.body ||
            ""
        );

        const snippet = escapeHTML(
            content.slice(0, 350)
        );

        const url = safeURL(item.url);

        const score = Number(item.skor ?? item.score ?? 0);

        const rank = item.rank ?? (index + 1);

        const scoreLabel = Number.isFinite(score)
            ? score.toFixed(4)
            : "0";

        return `
            <article class="result-card">

                <div class="result-tags">

                    <span class="result-tag ${sourceClass}">
                        ${sourceName}
                    </span>

                    <span class="result-tag">
                        RANK ${escapeHTML(rank)}
                    </span>

                    <span class="result-tag">
                        SCORE ${escapeHTML(scoreLabel)}
                    </span>

                </div>

                <h3>
                    ${title}
                </h3>

                <p>
                    ${snippet || "No preview available for this document."}
                    ${content.length > 350 ? "..." : ""}
                </p>

                <div class="result-meta">

                    <span>
                        ${escapeHTML(url || "No URL available")}
                    </span>

                    ${
                        url
                        ? `
                            <a
                                href="${escapeHTML(url)}"
                                target="_blank"
                                rel="noopener noreferrer"
                            >
                                OPEN SOURCE ↗
                            </a>
                        `
                        : ""
                    }

                </div>

            </article>
        `;
    }).join("");
}


// ==========================================
// SEARCH FORM EVENT
// ==========================================

if (searchForm) {
    searchForm.addEventListener("submit", function(event) {
        event.preventDefault();
        performSearch();
    });
}


// ==========================================
// SOURCE FILTER EVENT
// ==========================================

if (sourceFilter) {
    sourceFilter.addEventListener("change", function() {
        if (searchInput.value.trim()) {
            performSearch();
        }
    });
}


// ==========================================
// MODEL SELECT EVENT
// ==========================================

if (modelSelect) {
    modelSelect.addEventListener("change", function() {
        if (searchInput.value.trim()) {
            performSearch();
        }
    });
}


// ==========================================
// RESULT LIMIT EVENT
// ==========================================

if (resultLimit) {
    resultLimit.addEventListener("change", function() {
        if (searchInput.value.trim()) {
            performSearch();
        }
    });
}


// ==========================================
// QUERY EXPANSION EVENT
// ==========================================

if (expansionToggle) {
    expansionToggle.addEventListener("change", function() {
        if (searchInput.value.trim()) {
            performSearch();
        }
    });
}


// ==========================================
// QUICK SEARCH BUTTONS
// ==========================================

document.querySelectorAll(".quick-chip")
    .forEach(button => {
        button.addEventListener("click", function() {
            searchInput.value = button.dataset.query || "";

            performSearch();

            document.getElementById("search-section")
                ?.scrollIntoView({
                    behavior: "smooth"
                });
        });
    });


// ==========================================
// TOPIC CARD SEARCH
// ==========================================

document.querySelectorAll(".topic-card")
    .forEach(button => {
        button.addEventListener("click", function() {
            searchInput.value = button.dataset.search || "";

            performSearch();

            document.getElementById("search-section")
                ?.scrollIntoView({
                    behavior: "smooth"
                });
        });
    });


// ==========================================
// HERO COLLAGE SEARCH LINKS
// ==========================================

document.querySelectorAll(".collage-link")
    .forEach(link => {
        link.addEventListener("click", function(event) {
            event.preventDefault();

            searchInput.value = link.dataset.search || "";

            performSearch();

            document.getElementById("search-section")
                ?.scrollIntoView({
                    behavior: "smooth"
                });
        });
    });


// ==========================================
// INITIALIZE
// ==========================================

loadCorpus();
