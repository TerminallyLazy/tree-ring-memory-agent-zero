import { createStore } from "/js/AlpineStore.js";
import { callJsonApi } from "/js/api.js";

const apiPath = "/plugins/tree_ring_memory/memory_api";

const mutationActions = new Set([
    "remember",
    "evidence",
    "forget",
    "consolidate",
    "maintain",
    "sync_dox",
    "sync_revolve",
    "rebuild_fts",
]);

const settingsDefaults = {
    enabled: true,
    cli: {
        binary: "tree-ring",
        required_version: "0.13.0",
        timeout_seconds: 30,
    },
    storage: {
        root: "/a0/usr/memory/tree_ring_memory",
        legacy_sqlite_path: "/a0/usr/memory/tree_ring_memory/indexes/memory.sqlite",
    },
    scope: {
        default_project_scope: "current_project",
        allow_global: true,
        allow_cross_project_recall: false,
    },
    coordination: {
        coordinator_profiles: [],
    },
    recall: {
        max_results_default: 8,
        bridge_scan_limit: 100,
    },
    privacy: {
        include_sensitive_in_recall_by_default: false,
        export_requires_confirmation: true,
    },
    developer: {
        show_ranking_scores: false,
    },
};

function alpineStore(name) {
    try {
        return typeof globalThis.Alpine?.store === "function"
            ? globalThis.Alpine.store(name)
            : null;
    } catch {
        return null;
    }
}

function activeContextId() {
    const active = typeof globalThis.getContext === "function"
        ? String(globalThis.getContext() || "")
        : "";
    if (active) return active;
    return String(alpineStore("chats")?.getSelectedChatId?.() || "");
}

function currentContextId() {
    return String(alpineStore("treeRingMemory")?.writerContextId || activeContextId() || "");
}

function mergeMissing(target, defaults) {
    for (const [key, fallback] of Object.entries(defaults)) {
        if (fallback && typeof fallback === "object" && !Array.isArray(fallback)) {
            if (!target[key] || typeof target[key] !== "object" || Array.isArray(target[key])) {
                target[key] = {};
            }
            mergeMissing(target[key], fallback);
        } else if (target[key] === undefined || target[key] === null) {
            target[key] = Array.isArray(fallback) ? [...fallback] : fallback;
        }
    }
    return target;
}

async function post(action, payload = {}) {
    const contextId = currentContextId();
    const requiresWriter = mutationActions.has(action) || (action === "migrate" && Boolean(payload.confirm));
    if (requiresWriter && !contextId) {
        throw new Error("Choose a writer context or start a chat before changing Tree Ring Memory.");
    }
    const data = await callJsonApi(apiPath, {
        action,
        context_id: contextId,
        ...payload,
    });
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
    status: { ok: false, required_version: "0.13.0" },
    policy: { mode: "unknown", coordinator_label: null },
    policyAudit: [],
    searchBusy: false,
    maintenanceBusy: false,
    exportPath: "",
    settingsOpen: null,
    writerContextId: "",

    hydrateSettingsConfig(config) {
        if (!config || typeof config !== "object" || Array.isArray(config)) return false;
        mergeMissing(config, settingsDefaults);
        return true;
    },

    writerContexts() {
        const chatsStore = alpineStore("chats");
        const tasksStore = alpineStore("tasks");
        const chats = Array.isArray(chatsStore?.contexts) ? chatsStore.contexts : [];
        const tasks = Array.isArray(tasksStore?.tasks) ? tasksStore.tasks : [];
        const seen = new Set();
        return [...chats, ...tasks].filter((context) => {
            const id = String(context?.id || "");
            if (!id || seen.has(id)) return false;
            seen.add(id);
            return true;
        });
    },

    writerContextLabel(context) {
        if (!context) return "No writer context";
        const name = context.name || context.task_name;
        const fallback = context.no ? `Chat #${context.no}` : String(context.id || "Chat");
        const project = context.project?.name;
        return project ? `${name || fallback} · ${project}` : (name || fallback);
    },

    selectedWriterContext() {
        const id = currentContextId();
        return this.writerContexts().find((context) => String(context.id) === id) || null;
    },

    writerContextSummary() {
        const selected = this.selectedWriterContext();
        return selected
            ? `Mutations are attributed through ${this.writerContextLabel(selected)}.`
            : "Start a chat to establish an Agent Zero writer identity.";
    },

    syncWriterContext() {
        const contexts = this.writerContexts();
        const active = activeContextId();
        if (active) {
            this.writerContextId = active;
            return active;
        }
        if (this.writerContextId && contexts.some((context) => String(context.id) === this.writerContextId)) {
            return this.writerContextId;
        }
        this.writerContextId = String(contexts[0]?.id || "");
        return this.writerContextId;
    },

    hasWriterContext() {
        return Boolean(currentContextId());
    },

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
        this.syncWriterContext();
        await this.refreshStatus();
        if (this.status.ok) {
            await Promise.all([this.refreshStats(), this.refreshPolicy()]);
        }
    },

    async onOpen() {
        this.syncWriterContext();
        await this.refreshStatus();
        if (!this.status.ok) return;
        await Promise.all([this.refreshStats(), this.refreshPolicy()]);
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
            const response = await callJsonApi(apiPath, {
                action: "status",
                context_id: currentContextId(),
            });
            this.status = response.data || { ok: false, error: response.error || "Tree Ring CLI unavailable" };
        } catch (error) {
            this.status = { ok: false, error: error.message };
        }
    },

    async refreshPolicy() {
        try {
            const response = await post("policy_status");
            this.policy = response.data || { mode: "unknown", coordinator_label: null };
        } catch (error) {
            this.policy = { mode: "unavailable", coordinator_label: null };
            notify(error.message, "error");
        }
    },

    policyLabel() {
        const mode = String(this.policy?.mode || "unknown");
        const coordinator = this.policy?.coordinator_label;
        return coordinator ? `${mode} · ${coordinator}` : mode;
    },

    async remember(summary) {
        try {
            await post("remember", {
                memory: { summary, event_type: "lesson", scope: "agent" },
            });
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

    async schemaUpgrade(stage) {
        const action = stage === "apply" ? "apply_schema_upgrade" : "prepare_schema_upgrade";
        const message = stage === "apply"
            ? "Apply schema v3 now? The verified backup must already exist and every Tree Ring process must still be stopped."
            : "Create the pre-v0.13 backup now? Confirm every Tree Ring CLI, plugin, TUI, and worker using this root is stopped.";
        if (!window.confirm(message)) return;
        try {
            const response = await post(action, { confirm_offline: true });
            this.exportPath = response.data.backup_path || response.data.message || "";
            notify(response.data.message || "Schema upgrade step complete.", "success");
            await this.refreshStatus();
            if (this.status.ok) {
                await Promise.all([this.refreshStats(), this.refreshPolicy()]);
            }
        } catch (error) {
            notify(error.message, "error");
        }
    },

    async refreshPolicyAudit() {
        try {
            const response = await post("policy_audit", { limit: 50 });
            this.policyAudit = Array.isArray(response.data) ? response.data : [];
            this.exportPath = `${this.policyAudit.length} protected-write decisions loaded.`;
            notify("Policy audit loaded.", "success");
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
