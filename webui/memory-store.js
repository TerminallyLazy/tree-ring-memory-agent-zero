import { createStore } from "/js/AlpineStore.js";
import { callJsonApi } from "/js/api.js";

const apiPath = "/plugins/tree_ring_memory/memory_api";

async function post(action, payload = {}) {
    const data = await callJsonApi(apiPath, { action, ...payload });
    if (!data.ok) {
        throw new Error(data.error || "Tree Ring Memory request failed");
    }
    return data;
}

function notify(message, type = "info") {
    window.dispatchEvent(new CustomEvent("toast", { detail: { message, type } }));
}

export const store = createStore("treeRingMemory", {
    rings: ["cambium", "outer", "inner", "heartwood", "scar", "seed"],
    query: "",
    ring: "",
    eventType: "",
    includeSensitive: false,
    results: [],
    selected: null,
    stats: { counts: {} },
    status: { ok: false, required_version: "0.12.0" },
    searchBusy: false,
    maintenanceBusy: false,
    exportPath: "",
    settingsOpen: null,

    ensureSettingsUi() {
        if (this.settingsOpen) return;
        this.settingsOpen = {
            general: true,
            retention: false,
            privacy: false,
            integrations: false,
            developer: false,
        };
    },

    toggleSettingsSection(section) {
        this.ensureSettingsUi();
        this.settingsOpen[section] = !this.settingsOpen[section];
    },

    isSettingsSectionOpen(section) {
        this.ensureSettingsUi();
        return Boolean(this.settingsOpen[section]);
    },

    settingLabel(value, onLabel = "On", offLabel = "Off") {
        return value ? onLabel : offLabel;
    },

    ringLabel(ring) {
        const labels = {
            cambium: "Cambium",
            outer: "Outer",
            inner: "Inner",
            heartwood: "Heartwood",
            scar: "Scars",
            seed: "Seeds",
        };
        return labels[ring] || ring || "All rings";
    },

    ringCount(ring) {
        return Number((this.stats.counts || {})[ring]) || 0;
    },

    totalCount() {
        return this.rings.reduce((total, ring) => total + this.ringCount(ring), 0);
    },

    maxRingCount() {
        return Math.max(0, ...this.rings.map((ring) => this.ringCount(ring)));
    },

    ringUsagePercent(ring) {
        const maximum = this.maxRingCount();
        if (!maximum) return 0;
        return Math.round((this.ringCount(ring) / maximum) * 1000) / 10;
    },

    ringSharePercent(ring) {
        const total = this.totalCount();
        if (!total) return 0;
        return Math.round((this.ringCount(ring) / total) * 1000) / 10;
    },

    ringShareLabel(ring) {
        return `${this.ringSharePercent(ring).toFixed(1)}% of store`;
    },

    ringUsageLabel(ring) {
        return `${this.ringLabel(ring)}: ${this.ringCount(ring)} memories, ${this.ringShareLabel(ring)}`;
    },

    ringArcStyle(ring) {
        const usage = this.ringUsagePercent(ring);
        const opacity = usage ? Math.min(1, 0.5 + usage / 180) : 0;
        return `stroke-dasharray: ${usage} ${100 - usage}; opacity: ${opacity}; filter: drop-shadow(0 0 ${usage ? 4 : 0}px currentColor);`;
    },

    ringMeterStyle(ring) {
        return `width: ${this.ringUsagePercent(ring)}%;`;
    },

    dominantRingLabel() {
        const dominant = this.rings.reduce(
            (best, ring) => this.ringCount(ring) > this.ringCount(best) ? ring : best,
            this.rings[0],
        );
        return this.totalCount() ? `${this.ringLabel(dominant)} carries the canopy` : "Awaiting the first memory";
    },

    selectRing(ring) {
        this.ring = this.ring === ring ? "" : ring;
        return this.search();
    },

    clearFilters() {
        this.query = "";
        this.ring = "";
        this.eventType = "";
        this.includeSensitive = false;
        return this.search();
    },

    formatScore(value) {
        if (value === null || value === undefined || value === "") return "n/a";
        const number = Number(value);
        if (Number.isNaN(number)) return "n/a";
        return `${Math.round(number * 100)}%`;
    },

    sourceLabel(memory) {
        const source = memory?.source || {};
        const type = source.type || memory?.source_type || "source";
        const ref = source.ref || memory?.source_ref || "";
        return ref ? `${type}: ${ref}` : type;
    },

    resultMeta(memory) {
        const parts = [
            this.ringLabel(memory?.ring),
            memory?.event_type,
            `confidence ${this.formatScore(memory?.confidence)}`,
        ].filter(Boolean);
        return parts.join(" · ");
    },

    tagText(memory) {
        const tags = Array.isArray(memory?.tags) ? memory.tags : [];
        return tags.slice(0, 4).join(", ");
    },

    async init() {
        await this.refreshStatus();
        if (this.status.ok) await this.refreshStats();
    },

    async onOpen() {
        await this.refreshStatus();
        if (!this.status.ok) return;
        await this.refreshStats();
        if (!this.results.length) {
            await this.search();
        }
    },

    async search() {
        this.searchBusy = true;
        try {
            const rings = this.ring ? [this.ring] : undefined;
            const eventTypes = this.eventType ? [this.eventType] : undefined;
            const response = await post("search", {
                query: this.query || "",
                rings,
                event_types: eventTypes,
                include_sensitive: this.includeSensitive,
                limit: 8,
            });
            this.results = response.data.results || [];
            this.selected = this.results[0] || null;
        } catch (error) {
            notify(error.message, "error");
        } finally {
            this.searchBusy = false;
        }
    },

    select(memory) {
        this.selected = memory;
    },

    async refreshStats() {
        try {
            const response = await post("rings");
            this.stats = response.data || { counts: {} };
        } catch (error) {
            notify(error.message, "error");
        }
    },

    async refreshStatus() {
        try {
            const response = await callJsonApi(apiPath, { action: "status" });
            this.status = response.data || { ok: false, error: response.error || "Tree Ring CLI unavailable" };
        } catch (error) {
            this.status = { ok: false, error: error.message };
        }
    },

    async remember(summary) {
        try {
            await post("remember", { memory: { summary, event_type: "lesson" } });
            notify("Memory stored.", "success");
            await this.search();
            await this.refreshStats();
        } catch (error) {
            notify(error.message, "error");
        }
    },

    async mark(ring) {
        if (!this.selected) return;
        const eventType = ring === "scar" ? "warning" : ring === "seed" ? "hypothesis" : "lesson";
        try {
            await post("remember", {
                memory: {
                    summary: this.selected.summary,
                    event_type: eventType,
                    ring,
                    scope: this.selected.scope || "global",
                    project: this.selected.project || undefined,
                    tags: Array.from(new Set([...(this.selected.tags || []), `derived-from:${this.selected.id}`])),
                },
            });
            notify(`Created ${ring} memory.`, "success");
            await this.search();
            await this.refreshStats();
        } catch (error) {
            notify(error.message, "error");
        }
    },

    async forgetSelected(mode = "redact") {
        if (!this.selected) return;
        try {
            await post("forget", { memory_id: this.selected.id, mode, reason: `User requested ${mode} from Tree Ring Memory UI` });
            notify(`Memory ${mode} complete.`, "success");
            await this.search();
            await this.refreshStats();
        } catch (error) {
            notify(error.message, "error");
        }
    },

    async exportStore() {
        try {
            const response = await post("export", { format: "jsonl", include_sensitive: this.includeSensitive });
            this.exportPath = response.data.path || "";
            notify("Canonical JSONL export complete.", "success");
        } catch (error) {
            notify(error.message, "error");
        }
    },

    async developerAction(action) {
        try {
            const response = await post(action, action === "migrate" ? { confirm: false } : {});
            this.exportPath = response.data.path || response.data.export?.path || response.data.message || "";
            notify(action.replace("_", " ") + " complete.", "success");
        } catch (error) {
            notify(error.message, "error");
        }
    },

    async maintenance(action) {
        this.maintenanceBusy = true;
        try {
            const payload = action === "consolidate"
                ? { period_type: "daily" }
                : action === "sync_dox" || action === "sync_revolve"
                    ? { dry_run: true }
                    : {};
            await post(action, payload);
            const suffix = payload.dry_run ? " preview complete." : " complete.";
            notify(action.replace("_", " ") + suffix, "success");
            await this.search();
            await this.refreshStats();
        } catch (error) {
            notify(error.message, "error");
        } finally {
            this.maintenanceBusy = false;
        }
    },
});
