/**
 * Joblens - Content Script
 *
 * Injected into job platform pages (e.g., zhaopin.com) to parse job listings and details.
 * Communicates with the background script to manage queues and save results.
 */

export {};

declare global {
    interface Window {
        joblensGeneration?: number;
    }
}

(function() {
    // Avoid multiple injections
    window.joblensGeneration = (window.joblensGeneration ?? 0) + 1;
    const myGeneration = window.joblensGeneration;

    const harvestedJobs = new Map<string, any>();
    const isZhilianPage = window.location.hostname.includes('zhaopin.com');
    const isBossPage = window.location.hostname.includes('zhipin.com');
    const debugEnabled = window.location.href.includes("debug=1");
    const platform = isBossPage ? 'boss' : 'zhilian';
    const platformPfx = isBossPage ? 'BOSS' : 'ZHILIAN';
    const harvesterVersion = "v2.0.0";
    const harvestSessionKey = "joblensHarvesterSession";
    const keywordBatchSessionKey = "joblensKeywordBatchSession";
    const autoPageLimit = 30;
    const manualPageLimitMax = 50;

    type KeywordGroup = {
        category: string;
        group: string;
        keywords: string[];
    };

    type KeywordBatchSession = {
        active: boolean;
        keywords: string[];
        currentIndex: number;
        cityId: string;
        pageMode: string;
        updatedAt: string;
    };

    type HarvestPageStat = {
        page: number;
        added: number;
        total: number;
        restored: boolean;
        mode: "structured";
        searchKey: string;
        url: string;
        updatedAt: string;
    };

    type RawJobSnapshot = {
        titleText: string;
        cardText: string;
        cardHtml: string;
        capturedAt: string;
    };

    type ZhilianDetailResult = {
        status: "success" | "failed";
        jobUrl: string;
        requestedJobUrl?: string;
        finalUrl?: string;
        parseSource?: "initial_state" | "dom_fallback";
        detailTitle?: string;
        detailTags?: string[];
        salary?: string;
        companyName?: string;
        workAddress?: string;
        descriptionText?: string;
        companyIntro?: string;
        businessInfo?: {
            registeredName?: string;
            registeredCapital?: string;
            legalPerson?: string;
            setupDate?: string;
            businessScope?: string;
            epStatus?: string;
            industry?: string;
            location?: string;
        };
        raw?: {
            detailText: string;
            detailHtml?: string;
            detailHtmlFileName?: string;
            capturedAt: string;
            initialStateAvailable?: boolean;
        };
        error?: string;
    };

    const companyTypes = ["民营", "国企", "央企", "外企", "外商独资", "外资", "合资", "上市公司", "股份制企业", "事业单位", "社会团体", "其它", "其他"];
    const financingStages = ["未融资", "天使轮", "A轮", "B轮", "C轮", "D轮", "E轮", "战略融资", "已上市", "不需要融资"];
    const companySizePattern = /(\d+\s*-\s*\d+人|\d+人以下|\d+人以上)/;
    const companyBadgeKeywords = ["最佳雇主", "优选雇主", "高新技术企业"];
    const industryCandidates = [
        "计算机软件", "互联网", "IT服务", "软件/IT服务", "人工智能", "电子商务", "通信", "通信/网络设备", "半导体", "半导体/芯片", "智能硬件",
        "汽车", "新能源", "新能源汽车", "医疗设备", "医疗设备/器械/耗材", "制药", "医药制造", "金融", "基金", "证券", "证券/期货", "银行", "保险", "教育", "培训",
        "人力资源", "咨询", "咨询服务", "房地产", "房地产开发经营", "建筑", "物流", "货运物流", "供应链", "餐饮", "酒店", "零售", "批发",
        "仪器仪表", "船舶/航空/航天/军工", "航空/航天", "电子/半导体/集成电路", "工业自动化", "工业自动化/机器人",
        "机械设备", "计算机硬件", "云计算/大数据", "产业互联网平台", "快速消费品", "贸易/进出口", "投资与资产管理",
        "电气机械/电力设备", "技术服务", "学校/学历教育", "课外培训与资格考试", "文化艺术/娱乐", "化学原料/化学制品",
        "检测/认证/计量", "财务/审计/税务", "企业服务", "卫生服务", "食品/饮料/酒水批发/零售/贸易"
    ];

    function debugLog(label: string, payload?: unknown) {
        if (!debugEnabled) return;
        if (payload === undefined) {
            console.info(`[Joblens] ${label}`);
            return;
        }

        try {
            console.info(`[Joblens] ${label} ${JSON.stringify(payload)}`);
        } catch (e) {
            console.info(`[Joblens] ${label}`, payload);
        }
    }

    async function downloadTextFile(fileName: string, content: string, mimeType: string, isAuto: boolean): Promise<any> {
        const blob = new Blob([content], { type: mimeType });
        const reader = new FileReader();

        return new Promise(resolve => {
            reader.onload = async function() {
                const dataUrl = reader.result as string;
                try {
                    const response = await chrome.runtime.sendMessage({
                        action: "finalDownloadOnly",
                        dataUrl,
                        fileName,
                        isAuto
                    });
                    resolve(response);
                } catch (e) {
                    resolve({ success: false, error: e instanceof Error ? e.message : String(e) });
                }
            };
            reader.readAsDataURL(blob);
        });
    }

    function getJoblensPageLimit(): number {
        const params = new URLSearchParams(window.location.search);
        if (isHarvestTestMode()) return 1;
        const pageParam = params.get("joblens_pages");
        if (!pageParam || pageParam === "auto" || params.get("joblens_auto_pages") === "1") return autoPageLimit;
        const rawValue = parseInt(pageParam, 10);
        if (isNaN(rawValue) || rawValue < 1) return 1;
        return Math.min(rawValue, manualPageLimitMax);
    }

    function isAutoPagingMode(): boolean {
        if (isHarvestTestMode()) return false;
        const params = new URLSearchParams(window.location.search);
        const pageParam = params.get("joblens_pages");
        return !pageParam || pageParam === "auto" || params.get("joblens_auto_pages") === "1";
    }

    function isDetailTestMode(): boolean {
        const params = new URLSearchParams(window.location.search);
        return params.get("joblens_detail_test") === "1";
    }

    function getDetailTestLimit(): number {
        const params = new URLSearchParams(window.location.search);
        const rawValue = parseInt(params.get("joblens_detail_limit") || "3", 10);
        if (isNaN(rawValue) || rawValue < 1) return 3;
        return Math.min(rawValue, 5);
    }

    function isHarvestTestMode(): boolean {
        const params = new URLSearchParams(window.location.search);
        return params.get("joblens_test") === "1" || params.get("joblens_sample") === "1";
    }

    function isKeywordDiscoveryMode(): boolean {
        const params = new URLSearchParams(window.location.search);
        return params.get("joblens_keyword_discovery") === "1";
    }

    function isDirectJobDetailMode(): boolean {
        const params = new URLSearchParams(window.location.search);
        return params.get("detail") === "1";
    }

    function isDetailQueueWakeMode(): boolean {
        const params = new URLSearchParams(window.location.search);
        return params.get("joblens_detail_queue") === "1";
    }

    function isListQueueMode(): boolean {
        const params = new URLSearchParams(window.location.search);
        return params.get("joblens_list_queue") === "1";
    }

    function isListQueueWakeMode(): boolean {
        const params = new URLSearchParams(window.location.search);
        return params.get("joblens_list_queue_wake") === "1";
    }

    function getDirectJobDetailKeyword(): string {
        const params = new URLSearchParams(window.location.search);
        return cleanText(params.get("kw") || "job_detail");
    }

    function getBatchKeywordsParam(): string {
        const params = new URLSearchParams(window.location.search);
        return params.get("joblens_batch_keywords")
            || params.get("joblens_keywords")
            || "";
    }

    function parseBatchKeywords(rawValue?: string): string[] {
        return Array.from(new Set(
            (rawValue || "")
                .split(/[\n,|]/)
                .map(value => cleanText(value))
                .filter(Boolean)
        ));
    }

    function getBatchKeywordsFromParams(): string[] {
        return parseBatchKeywords(getBatchKeywordsParam());
    }

    function isKeywordBatchMode(): boolean {
        return getBatchKeywordsFromParams().length > 0;
    }

    function getPageModeKey(): string {
        if (isHarvestTestMode()) return "test";
        return isAutoPagingMode() ? "auto" : `limit:${getJoblensPageLimit()}`;
    }

    function decodeBase64Utf8(value: string | null): string {
        if (!value) return "";
        try {
            const normalizedValue = value.replace(/-/g, "+").replace(/_/g, "/");
            const paddedValue = normalizedValue.padEnd(Math.ceil(normalizedValue.length / 4) * 4, "=");
            const binary = atob(paddedValue);
            const bytes = Uint8Array.from(binary, char => char.charCodeAt(0));
            return cleanText(new TextDecoder().decode(bytes));
        } catch {
            return "";
        }
    }

    function encodeBase64Utf8(value: string): string {
        try {
            const bytes = new TextEncoder().encode(value);
            let binary = "";
            bytes.forEach(byte => {
                binary += String.fromCharCode(byte);
            });
            return btoa(binary).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/g, "");
        } catch {
            return "";
        }
    }

    function decodeMaybeEncodedKeyword(value: string | null): string {
        if (!value) return "";
        const text = cleanText(value);
        if (!text.includes("%")) return text;
        try {
            return cleanText(decodeURIComponent(text));
        } catch {
            return text;
        }
    }

    function getExplicitKeywordFromParams(params: URLSearchParams): string {
        return decodeBase64Utf8(params.get("kw64"))
            || decodeMaybeEncodedKeyword(params.get("kw"));
    }

    function getKeywordBatchSearchKey(): string {
        return [
            getTargetCityId(),
            getPageModeKey(),
            getBatchKeywordsFromParams().join("|")
        ].join("::");
    }

    function getCurrentPageFromUrl(): number {
        const url = new URL(window.location.href);
        const queryPage = parseInt(url.searchParams.get("p") || url.searchParams.get("page") || "", 10);
        if (!isNaN(queryPage) && queryPage > 0) return queryPage;

        const pathPage = url.pathname.match(/\/p(\d+)(?:\/)?$/);
        const pathPageNumber = pathPage ? parseInt(pathPage[1], 10) : NaN;
        return !isNaN(pathPageNumber) && pathPageNumber > 0 ? pathPageNumber : 1;
    }

    function getTargetCityId(): string {
        const params = new URLSearchParams(window.location.search);
        const cityFromParams = params.get("joblens_city")
            || params.get("cityId")
            || params.get("jl")
            || (params.get("city") === "上海" ? "538" : "");
        return /^\d+$/.test(cityFromParams || "") ? cityFromParams! : "538";
    }

    function getTargetCityName(): string {
        const cityMap: Record<string, string> = {
            "538": "上海",
            "530": "北京",
            "765": "广州",
            "763": "深圳",
            "653": "杭州",
            "101020100": "上海",
            "101010100": "北京",
            "101280100": "广州",
            "101280600": "深圳",
            "101210100": "杭州"
        };
        return cityMap[getTargetCityId()] || `城市${getTargetCityId()}`;
    }

    function getStableKeywordIdentity(): string {
        const url = new URL(window.location.href);
        const explicitKeyword = getExplicitKeywordFromParams(url.searchParams);
        if (explicitKeyword) return `keyword:${explicitKeyword}`;

        const pathKeyword = url.pathname.match(/\/kw([^/]+)/);
        if (pathKeyword?.[1]) return `pathkw:${pathKeyword[1]}`;

        const pageKeyword = cleanText(getKeywordFromPage());
        return `keyword:${pageKeyword || "Unknown"}`;
    }

    function getHarvestSearchKey(): string {
        return [
            getStableKeywordIdentity(),
            getTargetCityId(),
            isAutoPagingMode() ? "auto" : getJoblensPageLimit().toString()
        ].join("|");
    }

    function normalizeZhilianSearchUrl(pageNumber?: number): string {
        const url = new URL(window.location.href);
        const cityId = getTargetCityId();
        const hasPathKeyword = /\/kw[^/]+/.test(url.pathname);
        const explicitKeyword = getExplicitKeywordFromParams(url.searchParams);
        const keyword = explicitKeyword || (hasPathKeyword ? "" : cleanText(getKeywordFromPage()));

        if (/\/sou\/jl\d+\//.test(url.pathname)) {
            url.pathname = url.pathname.replace(/\/sou\/jl\d+\//, `/sou/jl${cityId}/`);
        } else {
            url.searchParams.set("jl", cityId);
        }

        url.searchParams.set("jl", cityId);
        url.searchParams.set("cityId", cityId);
        if (keyword && keyword !== "Unknown") {
            url.searchParams.set("kw", keyword);
            const keywordB64 = encodeBase64Utf8(keyword);
            if (keywordB64) url.searchParams.set("kw64", keywordB64);
        }
        if (url.searchParams.get("city") === "上海") {
            url.searchParams.delete("city");
        }

        if (typeof pageNumber === "number") {
            if (/\/p\d+(?:\/)?$/.test(url.pathname)) {
                url.pathname = url.pathname.replace(/\/p\d+(?:\/)?$/, `/p${pageNumber}`);
                url.searchParams.delete("p");
                url.searchParams.delete("page");
            } else {
                url.searchParams.set("p", String(pageNumber));
                url.searchParams.delete("page");
            }
        }

        return url.toString();
    }

    function shouldNormalizeZhilianSearchUrl(): boolean {
        if (!isZhilianPage || !window.location.href.includes("joblens_auto=1")) return false;
        const normalizedUrl = normalizeZhilianSearchUrl();
        return normalizedUrl !== window.location.href;
    }

    function getNextPageUrl(targetPage: number): string {
        const url = new URL(normalizeZhilianSearchUrl());
        if (/\/p\d+(?:\/)?$/.test(url.pathname)) {
            url.pathname = url.pathname.replace(/\/p\d+(?:\/)?$/, `/p${targetPage}`);
            return url.toString();
        }

        if (url.searchParams.has("page")) {
            url.searchParams.set("page", String(targetPage));
        } else {
            url.searchParams.set("p", String(targetPage));
        }
        return url.toString();
    }

    function buildKeywordSearchUrl(keyword: string, pageNumber: number = 1): string {
        const cityId = getTargetCityId();
        const url = new URL("https://sou.zhaopin.com/");
        url.searchParams.set("kw", keyword);
        url.searchParams.set("jl", cityId);
        url.searchParams.set("cityId", cityId);
        url.searchParams.set("joblens_auto", "1");
        url.searchParams.set("joblens_city", cityId);
        const keywordB64 = encodeBase64Utf8(keyword);
        if (keywordB64) url.searchParams.set("kw64", keywordB64);

        const pageParam = new URLSearchParams(window.location.search);
        if (!pageParam.has("joblens_pages") || pageParam.get("joblens_pages") === "auto") {
            url.searchParams.set("joblens_pages", "auto");
        } else if (pageParam.get("joblens_auto_pages") === "1") {
            url.searchParams.set("joblens_auto_pages", "1");
        } else {
            const pageLimit = getJoblensPageLimit();
            if (pageLimit > 1) {
                url.searchParams.set("joblens_pages", String(pageLimit));
            }
        }

        if (debugEnabled) {
            url.searchParams.set("debug", "1");
        }

        if (isHarvestTestMode()) {
            url.searchParams.set("joblens_test", "1");
        }

        const rawBatchKeywords = getBatchKeywordsParam();
        if (rawBatchKeywords) {
            url.searchParams.set("joblens_batch_keywords", rawBatchKeywords);
        }

        if (pageNumber > 1) {
            url.searchParams.set("p", String(pageNumber));
        }

        return url.toString();
    }

    async function readHarvestSession(): Promise<any | null> {
        try {
            const stored = await chrome.storage.local.get(harvestSessionKey);
            if (stored?.[harvestSessionKey]) return stored[harvestSessionKey];
        } catch (e) {}

        try {
            const raw = sessionStorage.getItem(harvestSessionKey);
            return raw ? JSON.parse(raw) : null;
        } catch (e) {
            return null;
        }
    }

    async function readKeywordBatchSession(): Promise<KeywordBatchSession | null> {
        try {
            const stored = await chrome.storage.local.get(keywordBatchSessionKey);
            if (stored?.[keywordBatchSessionKey]) return stored[keywordBatchSessionKey] as KeywordBatchSession;
        } catch (e) {}

        try {
            const raw = sessionStorage.getItem(keywordBatchSessionKey);
            return raw ? JSON.parse(raw) as KeywordBatchSession : null;
        } catch (e) {
            return null;
        }
    }

    function restoreHarvestSession(session: any | null) {
        harvestedJobs.clear();
        if (Array.isArray(session?.jobs)) {
            session.jobs.forEach((entry: any) => {
                if (Array.isArray(entry) && entry[0] && entry[1]) {
                    harvestedJobs.set(entry[0], entry[1]);
                }
            });
        }
    }

    function stripVolatileRawSnapshot(job: any): any {
        const { raw, ...rest } = job || {};
        return rest;
    }

    function escapeHtmlAttribute(value: string | undefined | null): string {
        return cleanText(value)
            .replace(/&/g, "&amp;")
            .replace(/"/g, "&quot;")
            .replace(/</g, "&lt;")
            .replace(/>/g, "&gt;");
    }

    function mergeHarvestPageStats(existingStats: HarvestPageStat[] | undefined, nextStat: HarvestPageStat): HarvestPageStat[] {
        const retained = (existingStats || []).filter(stat => stat.page !== nextStat.page);
        retained.push(nextStat);
        return retained.sort((a, b) => a.page - b.page);
    }

    async function saveHarvestSession(pageLimit: number, currentPage: number, lastGrowthPage?: number, pageStats?: HarvestPageStat[]) {
        const session = {
            active: true,
            pageLimit,
            currentPage,
            lastGrowthPage: lastGrowthPage || currentPage,
            keyword: getKeywordFromPage(),
            searchKey: getHarvestSearchKey(),
            autoPaging: isAutoPagingMode(),
            jobs: Array.from(harvestedJobs.entries()).map(([url, job]) => [url, stripVolatileRawSnapshot(job)]),
            pageStats: pageStats || [],
            updatedAt: new Date().toISOString()
        };

        try {
            await chrome.storage.local.set({ [harvestSessionKey]: session });
        } catch (e) {}

        try {
            sessionStorage.setItem(harvestSessionKey, JSON.stringify(session));
        } catch (e) {}
    }

    async function clearHarvestSession() {
        try {
            await chrome.storage.local.remove(harvestSessionKey);
        } catch (e) {}

        try {
            sessionStorage.removeItem(harvestSessionKey);
        } catch (e) {}
    }

    async function saveKeywordBatchSession(session: KeywordBatchSession) {
        try {
            await chrome.storage.local.set({ [keywordBatchSessionKey]: session });
        } catch (e) {}

        try {
            sessionStorage.setItem(keywordBatchSessionKey, JSON.stringify(session));
        } catch (e) {}
    }

    async function clearKeywordBatchSession() {
        try {
            await chrome.storage.local.remove(keywordBatchSessionKey);
        } catch (e) {}

        try {
            sessionStorage.removeItem(keywordBatchSessionKey);
        } catch (e) {}
    }

    function isSameKeyword(left: string, right: string): boolean {
        return cleanText(left) === cleanText(right);
    }

    async function ensureKeywordBatchSession(overlay?: HTMLElement): Promise<string | null> {
        const keywords = getBatchKeywordsFromParams();
        if (keywords.length === 0) return null;

        const pageMode = getPageModeKey();
        const cityId = getTargetCityId();
        const searchKey = getKeywordBatchSearchKey();
        const existing = await readKeywordBatchSession();
        const storedSearchKey = existing
            ? [existing.cityId, existing.pageMode, existing.keywords.join("|")].join("::")
            : "";

        const session = existing?.active && storedSearchKey === searchKey
            ? existing
            : {
                active: true,
                keywords,
                currentIndex: 0,
                cityId,
                pageMode,
                updatedAt: new Date().toISOString()
            };

        const currentKeyword = getKeywordFromPage();
        const targetKeyword = session.keywords[session.currentIndex] || keywords[0];
        await saveKeywordBatchSession({ ...session, updatedAt: new Date().toISOString() });

        if (!targetKeyword) return null;
        if (!isSameKeyword(currentKeyword, targetKeyword)) {
            if (overlay) {
                overlay.innerText = `Joblens (${harvesterVersion})\n批量模式：准备第 ${session.currentIndex + 1}/${session.keywords.length} 个关键词\n正在切换到：${targetKeyword}`;
            }
            return buildKeywordSearchUrl(targetKeyword, 1);
        }

        return null;
    }

    async function advanceKeywordBatch(overlay?: HTMLElement): Promise<boolean> {
        const session = await readKeywordBatchSession();
        if (!session?.active || session.keywords.length === 0) return false;

        const nextIndex = session.currentIndex + 1;
        if (nextIndex >= session.keywords.length) {
            await clearKeywordBatchSession();
            if (overlay) {
                overlay.style.background = "green";
                overlay.innerText = `✅ 批量采集完成\n关键词数量：${session.keywords.length}`;
            }
            return false;
        }

        const nextSession: KeywordBatchSession = {
            ...session,
            currentIndex: nextIndex,
            updatedAt: new Date().toISOString()
        };
        await saveKeywordBatchSession(nextSession);

        const nextKeyword = nextSession.keywords[nextSession.currentIndex];
        const nextUrl = buildKeywordSearchUrl(nextKeyword, 1);
        debugLog("batch advance", {
            nextIndex: nextSession.currentIndex,
            total: nextSession.keywords.length,
            nextKeyword,
            nextUrl
        });

        if (overlay) {
            overlay.style.background = "#2563eb";
            overlay.innerText = `Joblens (${harvesterVersion})\n批量模式：第 ${nextSession.currentIndex + 1}/${nextSession.keywords.length} 个关键词\n正在切换到：${nextKeyword}`;
        }

        window.location.replace(nextUrl);
        return true;
    }

    try {
        Object.defineProperty(document, 'visibilityState', { get: () => 'visible', configurable: true });
        Object.defineProperty(document, 'hidden', { get: () => false, configurable: true });
        document.dispatchEvent(new Event('visibilitychange'));
    } catch (e) {}

    function getKeywordFromPage(): string {
        try {
            const params = new URLSearchParams(window.location.search);
            const explicitKeyword = getExplicitKeywordFromParams(params);
            if (explicitKeyword) return explicitKeyword;
            const input = document.querySelector('.zp-search-input, input[placeholder*="职位"]') as HTMLInputElement;
            if (input?.value) return input.value.trim();
            const titleMatch = document.title.match(/^([^招聘]+)/);
            if (titleMatch) return titleMatch[1].trim();
        } catch (e) {}
        return "Unknown";
    }

    function cleanText(text: string | undefined | null): string {
        return (text || '').replace(/\s+/g, ' ').trim();
    }

    // BOSS icon-font salary decryption map
    const BOSS_FONT_MAP: Record<string, string> = {
        '': '0', '': '0', '': '1', '': '2',
        '': '3', '': '4', '': '5', '': '6',
        '': '7', '': '8', '': '9', '': '0',
    };

    function decryptBossSalary(element: HTMLElement): string {
        const html = element.innerHTML;
        const decoded = html.replace(/&#x([0-9a-fA-F]+);/g, (_match, hex) => {
            const char = String.fromCharCode(parseInt(hex, 16));
            return BOSS_FONT_MAP[char] || _match;
        });
        const temp = document.createElement('div');
        temp.innerHTML = decoded;
        const text = cleanText(temp.textContent);
        if (text && /[\dKk]/.test(text)) return text;
        // Fallback: extract from element text directly, also handling unicode chars
        const raw = element.textContent || '';
        let result = '';
        for (let i = 0; i < raw.length; i++) {
            const ch = raw[i];
            result += BOSS_FONT_MAP[ch] || ch;
        }
        const cleaned = cleanText(result);
        return cleaned && /[\dKk]/.test(cleaned) ? cleaned : text || cleanText(raw);
    }

    function extractBossSalaryFromText(text: string): string {
        const match = text.match(/(\d+)\s*[kK]?\s*[-~至]\s*(\d+)\s*[kK]/);
        if (match) return `${match[1]}-${match[2]}K`;
        const singleMatch = text.match(/(\d+)\s*[kK]/);
        if (singleMatch) return `${singleMatch[1]}K`;
        return '面议';
    }

    function isBossLoginWall(): boolean {
        if (window.location.href.includes('login.zhipin.com')) return true;
        const bodyText = (document.body.innerText || '').slice(0, 3000);
        // Detect BOSS login wall: various prompts asking user to log in or download the app
        return /登录后查看|请先登录|注册新账号|免费注册|下载App|去App|下载APP|开通BOSS|登录解锁|开通VIP|开通会员/.test(bodyText);
    }

    function hasSalaryText(text: string): boolean {
        return /(\d+(?:\.\d+)?\s*[-~至]\s*\d+(?:\.\d+)?\s*(?:K|k|W|w|万|千|元\/天|元)|\d+\s*-\s*\d+元\/天|\d+\s*-\s*\d+元|面议)/.test(text);
    }

    function escapeRegExp(value: string): string {
        return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
    }

    function hasToken(text: string, tokens: string[]): boolean {
        return tokens.some(token => new RegExp(`(^|[\\s·|/])${escapeRegExp(token)}([\\s·|/]|$)`).test(text));
    }

    function hasIndustryText(text: string): boolean {
        return industryCandidates.includes(text)
            || industryCandidates.some(candidate => new RegExp(`(^|[\\s·|])${escapeRegExp(candidate)}([\\s·|]|$)`).test(text));
    }

    function isCompanyMetaText(text: string): boolean {
        const normalized = cleanText(text);
        if (!normalized || normalized.length > 160) return false;

        const hasCompanyBadge = companyBadgeKeywords.some(badge => normalized.includes(badge));
        const hasCompanyType = companyTypes.includes(normalized) || hasToken(normalized, companyTypes);
        const hasFinancingStage = financingStages.some(stage => normalized.includes(stage));
        const hasCompanySize = companySizePattern.test(normalized);
        const hasIndustry = hasIndustryText(normalized);

        if (hasCompanyBadge && (hasCompanyType || hasCompanySize || hasIndustry || hasFinancingStage)) return true;
        if (hasCompanySize && (hasCompanyType || hasIndustry || hasFinancingStage)) return true;
        if (hasCompanyType && (hasIndustry || hasFinancingStage)) return true;
        if (hasFinancingStage && hasIndustry) return true;
        return false;
    }

    function stripRecruiterTail(value: string): string {
        return cleanText(value)
            .replace(/\s*(?:立即沟通|立即投递|投递|沟通).*$/, "")
            .replace(/\s*(?:今日回复\d+次|刚刚活跃|昨日活跃|\d+小时前(?:有回复|回复可能性大)?|\d+分钟内回复可能性大|高回复率).*$/, "")
            .replace(/\s*[\u4e00-\u9fa5A-Za-z]{1,12}[·.・]\s*(?:HRBP|HRM|HR|hr|招聘者|招聘专员|招聘经理|人事|人事经理|人事主管|人事专员|招聘主管|招聘专家|创始人兼CEO|CEO).*$/, "");
    }

    function getCompanyTailText(text: string, companyName: string): string {
        const normalizedText = cleanText(text);
        const normalizedCompanyName = cleanText(companyName);
        if (!normalizedCompanyName) return "";

        const index = normalizedText.indexOf(normalizedCompanyName);
        if (index < 0) return "";

        return stripRecruiterTail(normalizedText.slice(index + normalizedCompanyName.length));
    }

    function removeKnownCompanyMeta(value: string): string {
        let result = cleanText(value);
        [...companyBadgeKeywords, ...companyTypes, ...financingStages].forEach(token => {
            result = result.replace(new RegExp(`(^|\\s|[·|/])${escapeRegExp(token)}(?=\\s|[·|/]|$)`, "g"), " ");
        });
        result = result.replace(companySizePattern, " ");
        return cleanText(result).replace(/^[·\-/|]+|[·\-/|]+$/g, "");
    }

    function isLikelyIndustryCandidate(value: string): boolean {
        const candidate = cleanText(value).replace(/^[·\-/|]+|[·\-/|]+$/g, "");
        if (!candidate || candidate.length < 2 || candidate.length > 40) return false;
        if (!/[\u4e00-\u9fa5]/.test(candidate)) return false;
        if (hasSalaryText(candidate)) return false;
        if (normalizeAreaCandidate(candidate)) return false;
        if (companyTypes.includes(candidate) || financingStages.includes(candidate) || companySizePattern.test(candidate)) return false;
        if (companyBadgeKeywords.some(badge => candidate.includes(badge))) return false;
        if (/(经验不限|无经验|在校\/应届|应届|应届生|\d+\s*[-~至]\s*\d+\s*年|\d+\s*年以上|\d+\s*年|学历不限|本科|大专|硕士|博士|中专|高中|初中)/.test(candidate)) return false;
        if (/(立即沟通|立即投递|今日回复|刚刚活跃|昨日活跃|高回复率)/.test(candidate)) return false;
        if (/[·.・]\s*(?:HRBP|HRM|HR|hr|招聘者|招聘专员|招聘经理|人事|人事经理|人事主管|人事专员|招聘主管|招聘专家)/.test(candidate)) return false;
        return true;
    }

    function looksLikeJobCard(element: HTMLElement, anchor: HTMLAnchorElement): boolean {
        const text = cleanText(element.innerText);
        if (!text || text.length < 8 || text.length > 1200) return false;

        const jobLinks = Array.from(element.querySelectorAll("a[href*='/jobdetail/'], a[href*='/job_detail/']"));
        const normalizedAnchorUrl = anchor.href.split('?')[0];
        const containsCurrentAnchor = jobLinks.some(link => (link as HTMLAnchorElement).href.split('?')[0] === normalizedAnchorUrl);
        if (!containsCurrentAnchor || jobLinks.length > 2) return false;

        const titleCount = jobLinks
            .map(link => cleanText((link as HTMLElement).innerText))
            .filter(title => title.length >= 2).length;
        if (titleCount > 1 && text.length > 260) return false;

        const hasSalary = hasSalaryText(text) || Boolean(element.querySelector("[class*='salary'], [class*='Salary']"));
        const hasCompany = Boolean(element.querySelector("a[href*='/gongsi/'], a[href*='/companydetail/'], a[href*='company.zhaopin.com'], [class*='company'], [class*='Company']"));
        const hasArea = Boolean(element.querySelector(".job-area, .area-link, [class*='area'], [class*='Area'], [class*='city'], [class*='City']"))
            || /上海[·\-\u4e00-\u9fa5A-Za-z0-9]*/.test(text);

        return hasSalary && (hasCompany || hasArea);
    }

    function getElementScore(element: HTMLElement): number {
        const text = cleanText(element.innerText);
        const jobLinkCount = element.querySelectorAll("a[href*='/jobdetail/'], a[href*='/job_detail/']").length;
        let score = 0;

        if (jobLinkCount === 1) score += 60;
        if (hasSalaryText(text)) score += 25;
        if (element.querySelector("[class*='salary'], [class*='Salary']")) score += 15;
        if (element.querySelector("a[href*='/gongsi/'], a[href*='/companydetail/'], a[href*='company.zhaopin.com']")) score += 20;
        if (element.querySelector("[class*='company'], [class*='Company']")) score += 10;
        if (element.querySelector(".job-area, .area-link, [class*='area'], [class*='Area'], [class*='city'], [class*='City']")) score += 10;

        if (text.length > 500) score -= 20;
        if (text.length > 900) score -= 40;
        if (jobLinkCount > 1) score -= jobLinkCount * 30;

        return score;
    }

    function findJobCard(anchor: HTMLAnchorElement): HTMLElement | null {
        const candidates: HTMLElement[] = [];
        let card: HTMLElement | null = anchor;
        let depth = 0;

        while (card && card !== document.body && depth < 8) {
            if (looksLikeJobCard(card, anchor)) {
                candidates.push(card);
            }
            card = card.parentElement;
            depth++;
        }

        if (candidates.length > 0) {
            return candidates.sort((a, b) => getElementScore(b) - getElementScore(a))[0];
        }

        return anchor.closest("li, article, div[class*='job-card'], div[class*='jobCard']") as HTMLElement | null;
    }

    function extractSalary(card: HTMLElement): string {
        const salaryEl = card.querySelector("[class*='salary'], [class*='Salary'], [class*='welfare']") as HTMLElement | null;
        const salaryFromElement = cleanText(salaryEl?.innerText);
        if (salaryFromElement && /(\d|面议)/.test(salaryFromElement)) return salaryFromElement;

        const text = cleanText(card.innerText);
        const match = text.match(/(\d+(?:\.\d+)?\s*[-~至]\s*\d+(?:\.\d+)?\s*(?:K|k|W|w|万|千|元\/天|元)|\d+\s*-\s*\d+元\/天|\d+\s*-\s*\d+元|面议)/);
        return match ? match[1].replace(/\s+/g, '') : "面议";
    }

    const companyBadges = ["最佳雇主"];

    function splitCompanyBadges(value: string): { company: string; badges: string[] } {
        let company = cleanText(value);
        const badges: string[] = [];

        companyBadges.forEach(badge => {
            if (company.endsWith(badge)) {
                badges.push(badge);
                company = company.slice(0, -badge.length).trim();
            }
        });

        return { company: company || value, badges };
    }

    function isCleanCompanyNameCandidate(value: string, title: string): boolean {
        const text = cleanText(value);
        if (!text || text === title || text.includes("\n") || text.length > 80) return false;
        if (text.includes("查看详情") || hasSalaryText(text)) return false;
        if (companySizePattern.test(text)) return false;
        if (companyBadgeKeywords.some(badge => text.includes(badge))) return false;
        if (companyTypes.some(type => new RegExp(`(^|[\\s·|/])${escapeRegExp(type)}([\\s·|/]|$)`).test(text))) return false;
        if (financingStages.some(stage => text.includes(stage))) return false;
        if (hasIndustryText(text)) return false;
        if (/(立即沟通|立即投递|投递|沟通|高回复率|刚刚活跃|今日活跃|昨日活跃|\d+小时前(?:有回复|回复可能性大)?|\d+小时内回复可能性大|\d+分钟内回复可能性大|回复可能性大)/.test(text)) return false;
        if (/[·.・]\s*(?:HRBP|HRM|HR|hr|招聘者|招聘专员|招聘经理|招聘负责人|人事|人事经理|人事主管|人事专员|招聘主管|招聘专家|创始人兼CEO|CEO)/.test(text)) return false;
        return /[\u4e00-\u9fa5A-Za-z]/.test(text);
    }

    function getCleanCompanyFromElement(element: HTMLElement | null, title: string): { company: string; badges: string[] } | null {
        const text = cleanText(element?.innerText);
        const companyInfo = splitCompanyBadges(text);
        if (!isCleanCompanyNameCandidate(companyInfo.company, title)) return null;
        return companyInfo;
    }

    function extractCompany(card: HTMLElement, title: string): { company: string; companyUrl: string; companyBadges: string[] } {
        const preciseLinkSelectors = [
            "a[class*='companyinfo__name']",
            "a[class*='company-info__name']",
            "a[class*='companyInfo__name']",
            "a[href*='/gongsi/']",
            "a[href*='/companydetail/']",
            "a[href*='company.zhaopin.com']"
        ];

        for (const selector of preciseLinkSelectors) {
            const companyLinkEl = card.querySelector(selector) as HTMLAnchorElement | null;
            const companyInfo = getCleanCompanyFromElement(companyLinkEl, title);
            if (companyInfo) {
                return {
                    company: companyInfo.company,
                    companyUrl: companyLinkEl ? companyLinkEl.href.split('?')[0] : "",
                    companyBadges: companyInfo.badges
                };
            }
        }

        const preciseNameSelectors = [
            "[class*='companyinfo__name']",
            "[class*='company-info__name']",
            "[class*='companyInfo__name']",
            "[class*='company-name']",
            "[class*='companyName']"
        ];
        for (const selector of preciseNameSelectors) {
            const companyEl = card.querySelector(selector) as HTMLElement | null;
            const companyInfo = getCleanCompanyFromElement(companyEl, title);
            if (companyInfo) {
                const linkEl = companyEl?.closest("a") as HTMLAnchorElement | null;
                return {
                    company: companyInfo.company,
                    companyUrl: linkEl ? linkEl.href.split('?')[0] : "",
                    companyBadges: companyInfo.badges
                };
            }
        }

        const companyInfoRoot = card.querySelector("[class*='companyinfo'], [class*='company-info'], [class*='companyInfo']") as HTMLElement | null;
        if (companyInfoRoot) {
            const textNodes = Array.from(companyInfoRoot.querySelectorAll("a, span, p, div"))
                .map(element => element as HTMLElement)
                .filter(isVisibleElement)
                .filter(element => element.children.length === 0);

            for (const element of textNodes) {
                const companyInfo = getCleanCompanyFromElement(element, title);
                if (!companyInfo) continue;
                const linkEl = element.closest("a") as HTMLAnchorElement | null;
                return {
                    company: companyInfo.company,
                    companyUrl: linkEl ? linkEl.href.split('?')[0] : "",
                    companyBadges: companyInfo.badges
                };
            }
        }

        const companyLinkEl = card.querySelector("a[href*='/gongsi/'], a[href*='/companydetail/'], a[href*='company.zhaopin.com']") as HTMLAnchorElement | null;
        const linkTitle = cleanText(companyLinkEl?.getAttribute("title"));
        const titleCompanyInfo = splitCompanyBadges(linkTitle);
        if (isCleanCompanyNameCandidate(titleCompanyInfo.company, title)) {
            return {
                company: titleCompanyInfo.company,
                companyUrl: companyLinkEl ? companyLinkEl.href.split('?')[0] : "",
                companyBadges: titleCompanyInfo.badges
            };
        }

        return { company: "未知", companyUrl: "", companyBadges: [] };
    }

    const cityDistricts: Record<string, string[]> = {
        "北京": ["东城", "西城", "朝阳", "丰台", "石景山", "海淀", "门头沟", "房山", "通州", "顺义", "昌平", "大兴", "怀柔", "平谷", "密云", "延庆"],
        "上海": ["浦东", "黄浦", "徐汇", "长宁", "静安", "普陀", "虹口", "杨浦", "闵行", "宝山", "嘉定", "金山", "松江", "青浦", "奉贤", "崇明"],
        "广州": ["越秀", "荔湾", "海珠", "天河", "白云", "黄埔", "番禺", "花都", "南沙", "从化", "增城"],
        "深圳": ["罗湖", "福田", "南山", "宝安", "龙岗", "盐田", "龙华", "坪山", "光明", "大鹏"],
        "杭州": ["上城", "拱墅", "西湖", "滨江", "萧山", "余杭", "临平", "钱塘", "富阳", "临安", "桐庐", "淳安", "建德"]
    };

    const cityNames = Object.keys(cityDistricts);

    const areaStopWords = [
        "经验不限", "学历不限", "本科", "大专", "硕士", "博士", "中专", "高中", "初中",
        "全职", "兼职", "实习", "校园", "招聘", "职位", "岗位", "查看详情", "立即沟通"
    ];

    function stripAreaTailNoise(value: string): string {
        return value
            .replace(/(?:\d+\s*[-~至]\s*\d+\s*年|\d+\s*年以上|\d+\s*年|经验不限|本科|大专|硕士|博士|学历不限|中专|高中|初中).*$/, "")
            .trim();
    }

    function normalizeFreeformAreaCandidate(value: string): string {
        const candidate = stripAreaTailNoise(cleanText(value))
            .replace(/^(地点|地区|城市|工作地点|工作地区|地址)[:：]/, "")
            .replace(/\s*[·\-\\/|]\s*/g, "·")
            .replace(/\s+/g, "·")
            .replace(/新区/g, "")
            .replace(/([\u4e00-\u9fa5]{2,})(市|区)/g, "$1");

        const parts = candidate.split("·").filter(Boolean);
        const cleanParts = parts.filter(part => {
            if (!/[\u4e00-\u9fa5]/.test(part)) return false;
            if (/^\d+$/.test(part)) return false;
            if (/(?:\d+\s*[-~至]\s*\d+\s*年|\d+\s*年以上|\d+\s*年|经验不限|经验)/.test(part)) return false;
            if (part.length > 12) return false;
            return !areaStopWords.some(stopWord => part.includes(stopWord));
        }).slice(0, 3);

        if (cleanParts.length === 0) return "";
        return Array.from(new Set(cleanParts)).join("·");
    }

    function normalizeAreaCandidate(value: string): string {
        let candidate = stripAreaTailNoise(cleanText(value))
            .replace(/^(地点|地区|城市|工作地点|工作地区|地址)[:：]/, "")
            .replace(/\s*[·\-\\/|]\s*/g, "·")
            .replace(/\s+/g, "·")
            .replace(/市/g, "")
            .replace(/区/g, "")
            .replace(/新区/g, "");

        const directCity = cityNames.find(city => candidate.startsWith(city));
        if (!directCity) {
            for (const city of cityNames) {
                const district = cityDistricts[city].find(name => candidate.startsWith(name));
                if (district) {
                    candidate = `${city}·${candidate}`;
                    break;
                }
            }
        } else {
            candidate = candidate.replace(new RegExp(`^(${directCity})+`), directCity);
        }

        const parts = candidate.split("·").filter(Boolean);
        if (!cityNames.includes(parts[0])) return "";

        const cleanParts = parts.filter(part => {
            if (/^\d+$/.test(part)) return false;
            if (/(?:\d+\s*[-~至]\s*\d+\s*年|\d+\s*年以上|\d+\s*年|经验不限|经验)/.test(part)) return false;
            if (part.length > 12) return false;
            return !areaStopWords.some(stopWord => part.includes(stopWord));
        }).slice(0, 3);

        if (cleanParts.length === 0 || !cityNames.includes(cleanParts[0])) return "";
        return Array.from(new Set(cleanParts)).join("·");
    }

    function extractAreaBeforeRequirement(text: string): string {
        const requirementPattern = /(?:\d+\s*[-~至]\s*\d+\s*年|\d+\s*年以上|\d+\s*年|经验不限|本科|大专|硕士|博士|学历不限|中专|高中|初中)/;
        const lines = text.split(/\n+/).map(cleanText).filter(Boolean);

        for (const line of lines) {
            if (!requirementPattern.test(line)) continue;
            const area = normalizeFreeformAreaCandidate(line);
            if (area) return area;
        }

        return "";
    }

    function extractStructuredJobArea(card: HTMLElement): string {
        const otherInfoBlocks = Array.from(card.querySelectorAll("[class*='jobinfo__other-info'], [class*='job-info__other-info'], [class*='jobInfo__other-info']")) as HTMLElement[];
        for (const block of otherInfoBlocks) {
            const items = Array.from(block.children).map(child => child as HTMLElement).filter(isVisibleElement);
            for (const item of items) {
                const text = cleanText(item.innerText);
                if (!text) continue;
                const area = normalizeFreeformAreaCandidate(text);
                if (area && cityNames.includes(area.split("·")[0])) return area;
            }
        }

        return "";
    }

    function collectAreaCandidates(text: string): string[] {
        const candidates: string[] = [];
        const normalizedText = stripAreaTailNoise(cleanText(text))
            .replace(/市/g, "")
            .replace(/区/g, "")
            .replace(/\s*[·\-\\/|]\s*/g, "·");

        for (const city of cityNames) {
            const cityPattern = new RegExp(`${city}(?:[·\\s\\-/|][\\u4e00-\\u9fa5A-Za-z0-9]{1,12}){0,2}`, "g");
            const cityMatches = normalizedText.match(cityPattern) || [];
            candidates.push(...cityMatches);

            for (const district of cityDistricts[city]) {
                const districtPattern = new RegExp(`${district}(?:[·\\s\\-/|][\\u4e00-\\u9fa5A-Za-z0-9]{1,12}){0,1}`, "g");
                const districtMatches = normalizedText.match(districtPattern) || [];
                candidates.push(...districtMatches.map(match => `${city}·${match}`));
            }
        }

        return candidates
            .map(normalizeAreaCandidate)
            .filter(Boolean);
    }

    function getAreaScore(area: string): number {
        const parts = area.split("·").filter(Boolean);
        let score = parts.length * 20 + area.length;
        const districts = cityDistricts[parts[0]] || [];
        if (parts.some(part => districts.includes(part))) score += 30;
        if (parts.length === 1) score -= 50;
        return score;
    }

    function extractArea(card: HTMLElement): string {
        const selectors = [
            ".job-area",
            ".area-link",
            "[class*='area']",
            "[class*='Area']",
            "[class*='city']",
            "[class*='City']",
            "[class*='district']",
            "[class*='District']",
            "[class*='address']",
            "[class*='Address']",
            "[class*='location']",
            "[class*='Location']"
        ];

        const candidates: string[] = [];
        const structuredJobArea = extractStructuredJobArea(card);
        if (structuredJobArea) candidates.push(structuredJobArea);

        const structuredArea = extractAreaBeforeRequirement(card.innerText);
        if (structuredArea) candidates.push(structuredArea);

        card.querySelectorAll(selectors.join(",")).forEach(element => {
            const text = cleanText((element as HTMLElement).innerText);
            if (text) {
                const freeformArea = normalizeFreeformAreaCandidate(text);
                if (freeformArea) candidates.push(freeformArea);
                candidates.push(...collectAreaCandidates(text));
            }
        });

        candidates.push(...collectAreaCandidates(card.innerText));

        const uniqueCandidates = Array.from(new Set(candidates));
        const selectedArea = uniqueCandidates.length > 0
            ? uniqueCandidates.sort((a, b) => getAreaScore(b) - getAreaScore(a))[0]
            : "未知";

        if (uniqueCandidates.length > 0) {
            return selectedArea;
        }

        return selectedArea;
    }

    function extractRequirements(card: HTMLElement): { exp: string; edu: string } {
        const text = cleanText(card.innerText);
        const expMatch = text.match(/(经验不限|无经验|在校\/应届|应届|应届生|\d+\s*[-~至]\s*\d+\s*年|\d+\s*年以上|\d+\s*年)/);
        const eduMatch = text.match(/(学历不限|本科|大专|硕士|博士|中专\/中技|中专|高中|初中)/);

        return {
            exp: expMatch ? expMatch[1].replace(/\s+/g, '') : "未知",
            edu: eduMatch ? eduMatch[1] : "未知"
        };
    }

    function isVisibleElement(element: HTMLElement): boolean {
        const style = window.getComputedStyle(element);
        const rect = element.getBoundingClientRect();
        return style.display !== "none" && style.visibility !== "hidden" && rect.width > 0 && rect.height > 0;
    }

    function isNonSkillTag(tag: string): boolean {
        if (!tag || tag.length > 24) return true;
        if (hasSalaryText(tag)) return true;
        if (isCompanyMetaText(tag)) return true;
        if (companyBadgeKeywords.some(badge => tag.includes(badge))) return true;
        if (/^(经验不限|无经验|在校\/应届|应届|应届生|\d+\s*[-~至]\s*\d+\s*年|\d+\s*年以上|\d+\s*年)$/.test(tag)) return true;
        if (/^(学历不限|本科|大专|硕士|博士|中专\/中技|中专|高中|初中)$/.test(tag)) return true;
        if (/^(全职|兼职|实习|校园|招聘|职位|岗位|查看详情|立即沟通|面议)$/.test(tag)) return true;
        if (companyTypes.includes(tag) || financingStages.includes(tag) || companySizePattern.test(tag)) return true;
        if (normalizeAreaCandidate(tag)) return true;
        return false;
    }

    function hasNestedSkillCandidate(element: HTMLElement, selectors: string): boolean {
        return Array.from(element.querySelectorAll(selectors)).some(child => {
            const childEl = child as HTMLElement;
            return childEl !== element && isVisibleElement(childEl) && Boolean(cleanText(childEl.innerText));
        });
    }

    function isInsideCompanyMetaBlock(element: HTMLElement, card: HTMLElement): boolean {
        let parent = element.parentElement;
        let depth = 0;
        while (parent && parent !== card && depth < 5) {
            const text = cleanText(parent.innerText);
            if (isCompanyMetaText(text)) return true;
            parent = parent.parentElement;
            depth++;
        }
        return false;
    }

    function extractSkillTags(card: HTMLElement): string[] {
        const tagSelectors = [
            "[class*='tag']", "[class*='Tag']", "[class*='label']", "[class*='Label']", "[class*='skill']", "[class*='Skill']", "li"
        ];

        const tags: string[] = [];
        const selectorText = tagSelectors.join(",");
        const jobTagBlocks = Array.from(card.querySelectorAll("[class*='jobinfo__tag'], [class*='job-info__tag'], [class*='jobInfo__tag']")) as HTMLElement[];
        if (jobTagBlocks.length === 0) return [];

        const searchRoot: ParentNode = jobTagBlocks[0];

        searchRoot.querySelectorAll(selectorText).forEach(element => {
            const el = element as HTMLElement;
            if (!isVisibleElement(el)) return;

            const text = cleanText(el.innerText);
            if (!text || text.includes("\n")) return;
            if (isInsideCompanyMetaBlock(el, card)) return;
            if (hasNestedSkillCandidate(el, selectorText)) return;
            if (isNonSkillTag(text)) return;
            tags.push(text);
        });

        return normalizeSkillTags(tags).slice(0, 12);
    }

    function normalizeSkillTags(tags: string[]): string[] {
        const uniqueTags = Array.from(new Set(tags));
        return uniqueTags.filter(tag => {
            if (!/[\s,，、/]+/.test(tag)) return true;

            const parts = tag.split(/[\s,，、/]+/).map(cleanText).filter(Boolean);
            if (parts.length < 2) return true;

            const knownPartCount = parts.filter(part => uniqueTags.includes(part)).length;
            return knownPartCount < 2;
        });
    }

    function extractVisibleTagTexts(root: HTMLElement): string[] {
        return Array.from(root.querySelectorAll("[class*='tag'], [class*='Tag'], [class*='label'], [class*='Label']"))
            .map(element => element as HTMLElement)
            .filter(isVisibleElement)
            .map(element => cleanText(element.innerText))
            .filter(text => Boolean(text) && !text.includes("\n"));
    }

    function extractCompanyTagTexts(card: HTMLElement): string[] {
        const companyTagBlocks = Array.from(card.querySelectorAll("[class*='companyinfo__tag'], [class*='company-info__tag'], [class*='companyInfo__tag']")) as HTMLElement[];
        const tags = companyTagBlocks.flatMap(extractVisibleTagTexts);
        return Array.from(new Set(tags));
    }

    function extractCompanyMeta(card: HTMLElement, companyName: string): { companyType: string; financingStage: string; companySize: string; industry: string } {
        const lines = card.innerText.split(/\n+/).map(cleanText).filter(Boolean);
        const text = cleanText(card.innerText);
        const normalizedCompanyName = cleanText(companyName);
        const companyTailText = getCompanyTailText(text, normalizedCompanyName);
        const companyTagTexts = extractCompanyTagTexts(card);
        const isCompanyNameLine = (line: string) => Boolean(normalizedCompanyName && line === normalizedCompanyName);
        const isIndustryLine = (line: string) => hasIndustryText(line);
        const hasMetaMarker = (line: string) => financingStages.some(stage => line.includes(stage))
            || companySizePattern.test(line)
            || isIndustryLine(line);
        const isMetaTypeLine = (line: string) => companyTypes.includes(line)
            || companyTypes.some(type => new RegExp(`(^|[\\s·|/])${type}([\\s·|/]|$)`).test(line))
            || companyTypes.some(type => line.startsWith(type) && hasMetaMarker(line));
        const metaLines = lines.filter(line => {
            if (line.length > 100 || hasSalaryText(line) || isCompanyNameLine(line)) return false;
            return isMetaTypeLine(line)
                || financingStages.some(stage => line.includes(stage))
                || companySizePattern.test(line)
                || isIndustryLine(line);
        });
        const metaText = metaLines.join(" ");
        const searchText = metaText || companyTailText || text;
        const companyTypeFromTags = companyTagTexts.find(tag => companyTypes.includes(tag)
            || companyTypes.some(type => new RegExp(`(^|[\\s·|/])${escapeRegExp(type)}([\\s·|/]|$)`).test(tag)));
        const companyType = companyTypeFromTags || companyTypes.find(type =>
            metaLines.some(line => line === type
                || new RegExp(`(^|[\\s·|/])${type}([\\s·|/]|$)`).test(line)
                || (line.startsWith(type) && hasMetaMarker(line)))
            || new RegExp(`(^|[\\s·|/])${type}([\\s·|/]|$)`).test(companyTailText)
        ) || "未知";
        const financingStage = financingStages.find(stage => searchText.includes(stage)) || "未知";
        const companySizeFromTags = companyTagTexts.find(tag => companySizePattern.test(tag));
        const sizeMatch = (companySizeFromTags || searchText).match(companySizePattern);
        const companySize = sizeMatch ? sizeMatch[1].replace(/\s+/g, '') : "未知";
        const industryFromTags = companyTagTexts.find(tag => {
            if (tag === companyType || tag === financingStage || tag === companySize) return false;
            if (companyTypes.includes(tag) || financingStages.includes(tag) || companySizePattern.test(tag)) return false;
            return isLikelyIndustryCandidate(tag);
        });
        const industryLine = metaLines.find(line => industryCandidates.includes(line));
        const lineForIndustry = industryLine || metaLines.find(line => industryCandidates.some(candidate => line.includes(candidate)));
        const inferredIndustryFromTail = removeKnownCompanyMeta(companyTailText);

        let industry = "未知";
        if (industryFromTags) {
            industry = industryFromTags;
        } else if (isLikelyIndustryCandidate(inferredIndustryFromTail)) {
            industry = inferredIndustryFromTail;
        } else if (lineForIndustry) {
            let industryTail = lineForIndustry;
            if (companyType !== "未知") industryTail = industryTail.replace(companyType, "");
            if (financingStage !== "未知") industryTail = industryTail.replace(financingStage, "");
            if (companySize !== "未知") industryTail = industryTail.replace(companySizePattern, "");
            industryTail = cleanText(industryTail).replace(/^[·\-/|]+|[·\-/|]+$/g, "");
            const tailLooksValid = industryTail.length > 1
                && industryTail.length <= 40
                && !hasSalaryText(industryTail)
                && !/(经验不限|无经验|在校\/应届|应届|应届生|\d+\s*[-~至]\s*\d+\s*年|\d+\s*年以上|\d+\s*年|学历不限|本科|大专|硕士|博士|中专|高中|初中)/.test(industryTail);
            industry = tailLooksValid
                ? industryTail
                : industryCandidates.find(candidate => lineForIndustry.includes(candidate)) || "未知";
        }

        return { companyType, financingStage, companySize, industry };
    }

    function captureRawJobSnapshot(card: HTMLElement, title: string): RawJobSnapshot {
        return {
            titleText: title,
            cardText: card.innerText,
            cardHtml: card.outerHTML,
            capturedAt: new Date().toISOString()
        };
    }

    function createRawCardsHtml(rawSnapshot: any): string {
        const metadataJson = JSON.stringify(rawSnapshot.metadata, null, 2).replace(/<\/script/gi, "<\\/script");
        const sections = rawSnapshot.jobs.map((job: any) => {
            const raw = job.raw || {};
            return [
                `<section class="joblens-raw-card" data-index="${job.index}" data-job-url="${escapeHtmlAttribute(job.jobUrl)}" data-company-url="${escapeHtmlAttribute(job.companyUrl)}">`,
                `<!-- titleText: ${escapeHtmlAttribute(raw.titleText)} -->`,
                raw.cardHtml || "",
                `</section>`
            ].join("\n");
        }).join("\n\n");

        return [
            "<!doctype html>", "<html>", "<head>", "  <meta charset=\"utf-8\">",
            `  <title>Joblens Raw Cards - ${escapeHtmlAttribute(rawSnapshot.metadata.keyword)}</title>`,
            "</head>", "<body>",
            "  <script type=\"application/json\" id=\"joblens-raw-metadata\">",
            metadataJson,
            "  </script>",
            sections,
            "</body>", "</html>"
        ].join("\n");
    }

    function extractDetailTitle(): string {
        const selectors = ["h1", "[class*='job-name']", "[class*='jobName']", "[class*='position-name']", "[class*='title']"];
        for (const selector of selectors) {
            const element = document.querySelector(selector) as HTMLElement | null;
            const text = cleanText(element?.innerText || element?.textContent);
            if (text && text.length <= 80) return text;
        }
        return cleanText(document.title).replace(/[-_].*$/, "").trim();
    }

    function extractDetailWorkAddress(): string {
        const selectors = ["[class*='address']", "[class*='Address']", "[class*='location']", "[class*='Location']", "[class*='work-place']", "[class*='workPlace']"];
        for (const selector of selectors) {
            const elements = Array.from(document.querySelectorAll(selector)) as HTMLElement[];
            for (const element of elements) {
                const text = cleanText(element.innerText || element.textContent);
                const area = normalizeFreeformAreaCandidate(text);
                if (area) return area;
                if (text && text.length <= 120 && /[\u4e00-\u9fa5]/.test(text) && /(上海|北京|广州|深圳|杭州|浦东|徐汇|静安|闵行)/.test(text)) {
                    return text;
                }
            }
        }
        return "";
    }

    function extractDetailDescription(): string {
        const selectors = [
            "[class*='describ']", "[class*='Describ']", "[class*='description']", "[class*='Description']",
            "[class*='job-detail']", "[class*='jobDetail']", "[class*='position-detail']", "[class*='positionDetail']",
            "[class*='detail-content']", "[class*='detailContent']"
        ];
        const candidates = selectors
            .flatMap(selector => Array.from(document.querySelectorAll(selector)) as HTMLElement[])
            .map(element => cleanText(element.innerText || element.textContent))
            .filter(text => text.length >= 80)
            .sort((a, b) => b.length - a.length);
        if (candidates[0]) return candidates[0];

        const main = document.querySelector("main") as HTMLElement | null;
        const mainText = cleanText(main?.innerText);
        if (mainText && mainText.length >= 80) return mainText;

        return cleanText(document.body.innerText).slice(0, 6000);
    }

    function stripHtmlToReadableText(value: unknown): string {
        if (typeof value !== "string") return "";
        if (!/<[a-z][\s\S]*>/i.test(value)) return cleanText(value);
        const container = document.createElement("div");
        container.innerHTML = value.replace(/<br\s*\/?>/gi, "\n").replace(/<\/(div|p|li|section|article|h\d)>/gi, "\n");
        return cleanText(container.innerText || container.textContent);
    }

    function normalizeDetailStringArray(value: unknown): string[] {
        if (Array.isArray(value)) {
            return Array.from(new Set(value.flatMap(item => normalizeDetailStringArray(item)).map(item => cleanText(item)).filter(Boolean)));
        }
        if (typeof value === "string") {
            const text = cleanText(value);
            return text ? [text] : [];
        }
        if (value && typeof value === "object") {
            const record = value as Record<string, unknown>;
            return normalizeDetailStringArray(record.name || record.label || record.value || record.text || record.title);
        }
        return [];
    }

    function cleanUnknownText(value: unknown): string {
        return typeof value === "string" || typeof value === "number" ? cleanText(String(value)) : "";
    }

    function parseZhilianInitialState(): any | null {
        const scripts = Array.from(document.scripts).map(script => script.textContent || "").filter(text => text.includes("__INITIAL_STATE__"));
        for (const scriptText of scripts) {
            const assignmentIndex = scriptText.indexOf("__INITIAL_STATE__");
            const objectStart = scriptText.indexOf("{", assignmentIndex);
            const objectEnd = scriptText.lastIndexOf("}");
            if (objectStart < 0 || objectEnd <= objectStart) continue;
            try {
                return JSON.parse(scriptText.slice(objectStart, objectEnd + 1));
            } catch (error) {}
        }
        return null;
    }

    function extractDetailTagsFromInitialState(position: Record<string, unknown>): string[] {
        const candidateFields = [
            position.skillLabel, position.skillLabels, position.labels, position.positionLabel,
            position.positionLabels, position.tagList, position.tags, position.keywords
        ];
        return Array.from(new Set(candidateFields.flatMap(normalizeDetailStringArray)));
    }

    function parseDetailFromInitialState(state: any): Partial<ZhilianDetailResult> | null {
        const detailedPosition = state?.jobDetail?.detailedPosition || state?.detailedPosition || {};
        const detailedCompany = state?.jobDetail?.detailedCompany || state?.detailedCompany || {};
        const businessData = state?.companyExtDetail?.businessInformation?.businessInformationData || {};
        const position = detailedPosition as Record<string, unknown>;
        const company = detailedCompany as Record<string, unknown>;
        const biz = businessData as Record<string, unknown>;

        const descriptionText = stripHtmlToReadableText(position.description || position.jobDesc);
        const detailTitle = cleanUnknownText(position.positionName || position.jobName || position.name);
        if (!detailTitle && !descriptionText) return null;

        return {
            parseSource: "initial_state",
            detailTitle,
            detailTags: extractDetailTagsFromInitialState(position),
            salary: cleanUnknownText(position.salary),
            companyName: cleanUnknownText(company.companyName || position.companyName),
            workAddress: cleanUnknownText(position.workAddress),
            descriptionText,
            companyIntro: stripHtmlToReadableText(company.companyDescription || company.companyIntro),
            businessInfo: {
                registeredName: cleanUnknownText(biz.registeredName || company.companyName || position.companyName),
                registeredCapital: cleanUnknownText(biz.registeredCapital),
                legalPerson: cleanUnknownText(biz.legalPerson),
                setupDate: cleanUnknownText(biz.createDate),
                businessScope: stripHtmlToReadableText(biz.businessScope),
                epStatus: cleanUnknownText(biz.epStatus),
                industry: cleanUnknownText(biz.industry),
                location: cleanUnknownText(biz.location)
            }
        };
    }

    function isCaptchaPage(): boolean {
        const bodyText = document.body.innerText || "";
        const title = document.title || "";
        const url = window.location.href;
        const sample = bodyText.slice(0, 4000);
        return (
            /验证码|人机验证|安全验证|拦截/.test(title) ||
            /验证码|人机验证|安全验证|请完成验证|点击验证|正在验证连接安全性|请勾选下方复选框|验证完成后.*重定向|Tencent Cloud EdgeOne|Protected by Tencent Cloud EdgeOne/i.test(sample) ||
            /captcha|verify|challenge/i.test(url)
        );
    }

    function parseZhilianDetailPage(): ZhilianDetailResult {
        try {
            if (isCaptchaPage()) {
                return { status: "failed", jobUrl: window.location.href.split("?")[0], error: "security verification page detected" };
            }
            const initialState = parseZhilianInitialState();
            const initialStateDetail = initialState ? parseDetailFromInitialState(initialState) : null;
            return {
                status: "success",
                jobUrl: window.location.href.split("?")[0],
                parseSource: initialStateDetail?.parseSource || "dom_fallback",
                detailTitle: initialStateDetail?.detailTitle || extractDetailTitle(),
                detailTags: initialStateDetail?.detailTags || [],
                salary: initialStateDetail?.salary,
                companyName: initialStateDetail?.companyName,
                workAddress: initialStateDetail?.workAddress || extractDetailWorkAddress(),
                descriptionText: initialStateDetail?.descriptionText || extractDetailDescription(),
                companyIntro: initialStateDetail?.companyIntro,
                businessInfo: initialStateDetail?.businessInfo,
                raw: {
                    detailText: document.body.innerText,
                    detailHtml: document.documentElement.outerHTML,
                    capturedAt: new Date().toISOString(),
                    initialStateAvailable: Boolean(initialState)
                }
            };
        } catch (error) {
            return { status: "failed", jobUrl: window.location.href.split("?")[0], error: error instanceof Error ? error.message : String(error) };
        }
    }

    function normalizeZhilianJobIdentity(url: string): string {
        try {
            const parsed = new URL(url, window.location.href);
            const match = parsed.pathname.match(/\/job_?detail\/([^/?#]+)/i);
            if (match?.[1]) return match[1].toLowerCase();
            return `${parsed.hostname}${parsed.pathname}`.replace(/^www\./, "").toLowerCase();
        } catch {
            return String(url || "").split("?")[0].replace(/^https?:\/\//i, "").replace(/^www\./i, "").toLowerCase();
        }
    }

    function sanitizeArtifactNamePart(value: string, fallback: string): string {
        const sanitized = cleanText(value).replace(/[\/\\?%*:|"<>]/g, "-").replace(/[\x00-\x1f\x80-\x9f]/g, "").replace(/\s+/g, "_").slice(0, 80);
        return sanitized || fallback;
    }

    function getZhilianJobIdForFile(url: string, index: number): string {
        const identity = normalizeZhilianJobIdentity(url);
        const match = identity.match(/(cc[a-z0-9]+j[a-z0-9]+)/i);
        return sanitizeArtifactNamePart(match?.[1] || identity || `job_${index}`, `job_${index}`);
    }

    function cloneDetailWithoutEmbeddedHtml(detail: ZhilianDetailResult, detailHtmlFileName?: string): ZhilianDetailResult {
        const raw = detail.raw ? { ...detail.raw } : undefined;
        if (raw) {
            delete raw.detailHtml;
            if (detailHtmlFileName) raw.detailHtmlFileName = detailHtmlFileName;
        }
        return { ...detail, raw };
    }

    function buildDetailMarkdownFileName(job: any): string {
        const companyName = sanitizeArtifactNamePart(job.company || "未知公司", "unknown_company");
        const jobTitle = sanitizeArtifactNamePart(job.title || "未知岗位", "unknown_job");
        return `${companyName}_${jobTitle}.md`;
    }

    function createSingleDetailMarkdown(job: any, detail: ZhilianDetailResult, metadata: any): string {
        let content = `---\nsource: zhilian\nkeyword: ${metadata.keyword}\ncompany: ${job.company}\ntitle: ${job.title}\nurl: ${job.url}\ncollected: ${metadata.collectedAt}\n---\n\n`;
        content += `# ${job.company}_${job.title}\n\n`;
        content += `- 来源：智联招聘\n- 状态：详情页采集\n- 公司：[${job.company}](${job.companyUrl})\n- 列表地点：${job.area || "未知"}\n- 列表薪资：${job.salary || "未知"}\n- 列表经验：${job.exp || "未知"}\n- 列表学历：${job.edu || "未知"}\n- 岗位链接：[查看详情](${job.url})\n- 采集URL：${window.location.href}\n- 时间：${new Date().toLocaleString()}\n\n`;
        content += `## 详情字段\n\n- 详情状态：${detail.status}\n`;
        if (detail.status === "failed") {
            content += `- 失败原因：${detail.error || "未知"}\n`;
            return content;
        }
        content += `- 解析来源：${detail.parseSource || "未知"}\n- 详情标题：${detail.detailTitle || "未知"}\n- 详情薪资：${detail.salary || "未知"}\n- 详情公司：${detail.companyName || "未知"}\n- 详情地址：${detail.workAddress || "未知"}\n- 详情 Raw HTML：${detail.raw?.detailHtmlFileName || "未知"}\n\n`;
        content += `## 详情岗位标签\n\n${detail.detailTags?.length ? detail.detailTags.map(tag => `- ${tag}`).join("\n") : "- 未提供"}\n\n`;
        content += `## 职位详情全文\n\n${detail.descriptionText || "未知"}\n\n`;
        if (detail.companyIntro) content += `## 公司介绍\n\n${detail.companyIntro}\n\n`;
        if (detail.businessInfo && Object.values(detail.businessInfo).some(Boolean)) {
            content += `## 工商信息摘要\n\n- 注册名称：${detail.businessInfo.registeredName || "未知"}\n- 注册资本：${detail.businessInfo.registeredCapital || "未知"}\n- 法定代表人：${detail.businessInfo.legalPerson || "未知"}\n- 成立时间：${detail.businessInfo.setupDate || "未知"}\n- 登记状态：${detail.businessInfo.epStatus || "未知"}\n- 工商行业：${detail.businessInfo.industry || "未知"}\n- 工商地址：${detail.businessInfo.location || "未知"}\n`;
            if (detail.businessInfo.businessScope) content += `\n## 经营范围\n\n${detail.businessInfo.businessScope}\n`;
        }
        return content;
    }

    async function exportDirectJobDetailResult(overlay: HTMLElement) {
        const now = new Date();
        const timestamp = now.getFullYear().toString() + (now.getMonth() + 1).toString().padStart(2, '0') + now.getDate().toString().padStart(2, '0') + '_' + now.getHours().toString().padStart(2, '0') + now.getMinutes().toString().padStart(2, '0') + now.getSeconds().toString().padStart(2, '0');
        const keyword = getDirectJobDetailKeyword();
        const detail = parseZhilianDetailPage();
        const job = {
            title: detail.detailTitle || document.title || "未知岗位",
            company: detail.companyName || "未知公司",
            companyUrl: window.location.origin,
            area: detail.workAddress || "未知",
            salary: detail.salary || "未知",
            exp: "未知",
            edu: "未知",
            url: detail.jobUrl || window.location.href.split("?")[0]
        };
        const metadata = { platform: "zhilian", keyword, url: window.location.href, collectedAt: now.toISOString(), mode: "job_detail", harvesterVersion };
        const companyName = sanitizeArtifactNamePart(job.company, "unknown_company");
        const jobTitle = sanitizeArtifactNamePart(job.title, "unknown_job");
        const markdownFileName = `ZHILIAN_DETAIL_${companyName}_${jobTitle}_${timestamp}.md`;
        const jobId = getZhilianJobIdForFile(job.url, 1);
        const rawHtmlFileName = `ZHILIAN_DETAIL_RAW_${timestamp}_${jobId}.html`;
        const manifestFileName = `ZHILIAN_DETAIL_MANIFEST_${timestamp}_${jobId}.json`;

        const urlParams = new URLSearchParams(window.location.search);
        const saveHtml = urlParams.get("html") === "1";
        const saveJson = urlParams.get("json") === "1";

        if (saveHtml && detail.raw?.detailHtml) {
            await downloadTextFile(rawHtmlFileName, detail.raw.detailHtml, "text/html", true);
            detail.raw.detailHtmlFileName = rawHtmlFileName;
            delete detail.raw.detailHtml;
        }

        const markdownResponse = await downloadTextFile(markdownFileName, createSingleDetailMarkdown(job, detail, metadata), "text/markdown", true);
        if (saveJson) await downloadTextFile(manifestFileName, JSON.stringify({ metadata, markdownFileName, rawHtmlFileName, job, detail }, null, 2), "application/json", true);

        if (!markdownResponse?.success || detail.status === "failed") {
            if (isCaptchaPage()) {
                overlay.style.background = "red";
                overlay.innerText = `⚠️ 验证码拦截！\n请手动完成人机验证`;
                chrome.runtime.sendMessage({ action: "captchaDetected" }).catch(() => {});
                return;
            }
        }

        if (markdownResponse?.success) {
            overlay.style.background = "green";
            overlay.innerText = `✅ 详情采集完成\n${job.company}\n${job.title}`;
        } else {
            overlay.style.background = "#9a3412";
            overlay.innerText = `详情文件下载失败：${markdownResponse?.error || "未知错误"}`;
        }

        setTimeout(() => { chrome.runtime.sendMessage({ action: "closeCurrentTab" }).catch(() => { window.close(); }); }, 1500);
    }

    async function scanAndHarvest(overlay?: HTMLElement) {
        const jobLinks = document.querySelectorAll("a[href*='/job_detail/'], a[href*='/jobdetail/']");
        jobLinks.forEach(link => {
            try {
                const anchor = link as HTMLAnchorElement;
                const fullUrl = anchor.href.split('?')[0];
                const title = cleanText(anchor.innerText);
                if (harvestedJobs.has(fullUrl)) return;
                if (title.length < 2) return;
                const card = findJobCard(anchor);
                if (card) {
                    const company = extractCompany(card, title);
                    const requirements = extractRequirements(card);
                    const companyMeta = extractCompanyMeta(card, company.company);
                    harvestedJobs.set(fullUrl, {
                        title, url: fullUrl, salary: extractSalary(card), exp: requirements.exp, edu: requirements.edu,
                        skills: extractSkillTags(card), company: company.company, companyUrl: company.companyUrl,
                        companyBadges: company.companyBadges, area: extractArea(card),
                        companyType: companyMeta.companyType, financingStage: companyMeta.financingStage,
                        companySize: companyMeta.companySize, industry: companyMeta.industry,
                        raw: captureRawJobSnapshot(card, title)
                    });
                    if (overlay) overlay.innerText = `Joblens (${harvesterVersion})\n已捕获：${harvestedJobs.size} 个岗位...`;
                }
            } catch (e) {}
        });
    }

    async function autoScroll(harvest: boolean = false, overlay?: HTMLElement) {
        let lastHeight = document.body.scrollHeight;
        let sameHeightCount = 0;
        while (sameHeightCount < 4) {
            if (harvest) await scanAndHarvest(overlay);
            window.scrollBy(0, 1500);
            window.dispatchEvent(new Event('scroll'));
            window.dispatchEvent(new Event('resize'));
            await new Promise(r => setTimeout(r, 800));
            const currentHeight = document.body.scrollHeight;
            if (currentHeight === lastHeight) sameHeightCount++;
            else { sameHeightCount = 0; lastHeight = currentHeight; }
            if ((window.innerHeight + window.scrollY) >= document.body.offsetHeight - 200) await new Promise(r => setTimeout(r, 1500));
        }
        if (harvest) await scanAndHarvest(overlay);
        window.scrollTo(0, 0);
    }

    function getCategoryTitle(item: HTMLElement): string {
        const titleEl = item.querySelector("[class*='job-menu__name'], [class*='menu__name'], [class*='title']") as HTMLElement | null;
        const title = cleanText(titleEl?.innerText || titleEl?.textContent);
        return (title || "").replace(/[>›]+$/, "").trim();
    }

    async function discoverZhilianKeywords(overlay?: HTMLElement): Promise<KeywordGroup[]> {
        await new Promise(r => setTimeout(r, 1500));
        const categoryItems = Array.from(document.querySelectorAll(".job-menu__item, [class*='job-menu__item']")).filter(item => item instanceof HTMLElement) as HTMLElement[];
        const allGroups: KeywordGroup[] = [];
        for (const item of categoryItems) {
            const category = getCategoryTitle(item);
            if (!category) continue;
            if (overlay) overlay.innerText = `Joblens (${harvesterVersion})\n正在展开：${category}\n已发现分组：${allGroups.length}`;
            item.scrollIntoView({ block: "center", inline: "nearest" });
            ["mouseenter", "mouseover", "mousemove"].forEach(type => item.dispatchEvent(new MouseEvent(type, { bubbles: true, cancelable: true, view: window })));
            await new Promise(r => setTimeout(r, 700));
            const panel = document.querySelector(".job-menu__sub, [class*='job-menu__sub']") as HTMLElement | null;
            if (panel) {
                const groupedKeywords = new Map<string, string[]>();
                let currentGroup = "";
                panel.querySelectorAll(".job-menu__sub__title, [class*='job-menu__sub__title'], .job-menu__sub__name__text, [class*='job-menu__sub__name__text']").forEach(node => {
                    const text = cleanText((node as HTMLElement).innerText);
                    if ((node as HTMLElement).matches(".job-menu__sub__title, [class*='job-menu__sub__title']")) currentGroup = text;
                    else if (currentGroup && text) {
                        const keywords = groupedKeywords.get(currentGroup) || [];
                        if (!keywords.includes(text)) { keywords.push(text); groupedKeywords.set(currentGroup, keywords); }
                    }
                });
                allGroups.push(...Array.from(groupedKeywords.entries()).map(([group, keywords]) => ({ category, group, keywords })));
            }
        }
        return allGroups;
    }

    async function discoverBossKeywords(overlay?: HTMLElement): Promise<KeywordGroup[]> {
        const allGroups: KeywordGroup[] = [];
        const menuSubs = document.querySelectorAll('div.menu-sub');
        for (const menuSub of menuSubs) {
            const article = menuSub.querySelector('p.menu-article');
            const category = cleanText((article as HTMLElement)?.innerText || '');
            if (!category) continue;
            if (overlay) overlay.innerText = `Joblens (${harvesterVersion})\nBOSS 正在解析：${category}\n已发现分组：${allGroups.length}`;
            const listItems = menuSub.querySelectorAll('li');
            for (const li of listItems) {
                const h4 = li.querySelector('h4');
                const group = cleanText((h4 as HTMLElement)?.innerText || '');
                if (!group) continue;
                const textDiv = li.querySelector('div.text');
                if (!textDiv) continue;
                const links = textDiv.querySelectorAll('a[ka*="search_"]');
                const keywords: string[] = [];
                links.forEach(a => {
                    const name = cleanText((a as HTMLElement).innerText);
                    if (name) keywords.push(name);
                });
                if (keywords.length > 0) {
                    allGroups.push({ category, group, keywords });
                }
            }
            await new Promise(r => setTimeout(r, 30));
        }
        return allGroups;
    }

    async function exportKeywordDiscoveryResult(groups: KeywordGroup[], overlay?: HTMLElement) {
        const now = new Date();
        const timestamp = now.getFullYear().toString() + (now.getMonth() + 1).toString().padStart(2, '0') + now.getDate().toString().padStart(2, '0') + '_' + now.getHours().toString().padStart(2, '0') + now.getMinutes().toString().padStart(2, '0') + now.getSeconds().toString().padStart(2, '0');
        const pfx = isBossPage ? 'boss_keyword_discovery' : 'zhilian_keyword_discovery';
        const fileName = `${pfx}_${timestamp}.md`;
        const title = isBossPage ? 'BOSS直聘' : '智联';
        const sourceLabel = isBossPage ? 'BOSS直聘SEO页面' : '智联招聘首页职位分类';
        const categories = Array.from(new Set(groups.map(g => g.category)));
        const categoryCount = categories.length;
        const subCategoryCount = groups.length;
        const keywordCount = groups.reduce((sum, g) => sum + g.keywords.length, 0);
        let content = `# ${title}岗位关键词池：${getTargetCityName()}\n\n`;
        content += `- 来源：${sourceLabel}\n`;
        content += `- 状态：✅ 关键词发现成功\n`;
        content += `- 一级分类数：${categoryCount}\n`;
        content += `- 二级分组数：${subCategoryCount}\n`;
        content += `- 去重岗位词数：${keywordCount}\n`;
        content += `- 采集URL：${window.location.href}\n`;
        content += `- 时间：${new Date().toLocaleString()}\n\n`;
        categories.forEach(c => {
            content += `## ${c}\n\n`;
            groups.filter(g => g.category === c).forEach(g => {
                content += `### ${g.group}\n${g.keywords.map(k => `- ${k}`).join("\n")}\n\n`;
            });
        });
        await downloadTextFile(fileName, content, 'text/markdown', true);
        if (overlay) { overlay.style.background = "green"; overlay.innerText = "✅ 关键词发现完成"; }
    }

    async function triggerFinalSave(isAuto: boolean, overlay?: HTMLElement) {
        await scanAndHarvest(overlay);
        const keyword = getKeywordFromPage();
        const now = new Date();
        const timestamp = now.getFullYear().toString() + (now.getMonth() + 1).toString().padStart(2, '0') + now.getDate().toString().padStart(2, '0') + '_' + now.getHours().toString().padStart(2, '0') + now.getMinutes().toString().padStart(2, '0') + now.getSeconds().toString().padStart(2, '0');
        const fileName = isHarvestTestMode() ? `ZHILIAN_TEST_${keyword}_${timestamp}.md` : `ZHILIAN_${keyword}_${timestamp}.md`;
        const jobs = Array.from(harvestedJobs.values());
        let content = `# 智联岗位收割：${keyword}\n\n- 数量：${jobs.length}\n- 时间：${new Date().toLocaleString()}\n\n## 岗位列表\n\n`;
        jobs.forEach((r, idx) => {
            content += `### ${idx + 1}. ${r.title}\n- 公司：[${r.company}](${r.companyUrl})\n- 薪资：**${r.salary}**\n- 地点：${r.area}\n- 链接：[查看详情](${r.url})\n\n`;
        });
        const response = await downloadTextFile(fileName, content, "text/markdown", isAuto);
        if (response?.success && isAuto && overlay) { overlay.style.background = "green"; overlay.innerText = "✅ 采集完成"; }
        if (isAuto && isListQueueMode()) {
            await chrome.runtime.sendMessage({ action: "zhilianListHarvestDone", success: Boolean(response?.success), keyword, fileName });
            await chrome.runtime.sendMessage({ action: "closeCurrentTab" });
        }
    }

    // --- BOSS直聘 list harvesting ---

    function findBossJobCard(anchor: HTMLAnchorElement): HTMLElement | null {
        let card: HTMLElement | null = anchor;
        let depth = 0;
        while (card && card !== document.body && depth < 12) {
            const text = cleanText(card.innerText);
            const hasCompanyLink = Boolean(card.querySelector("a[href*='/gongsi/'], a[href*='/company/']"));
            const hasSalary = /[-Kk薪]/.test(card.innerText);
            if (text && text.length >= 30 && text.length <= 1500 && hasCompanyLink && hasSalary) {
                return card;
            }
            card = card.parentElement;
            depth++;
        }
        return anchor.closest("li, [class*='job-card'], [class*='jobCard'], [class*='job-item'], [class*='jobItem']") as HTMLElement | null;
    }

    // Decode all BOSS font-encrypted chars in a string using BOSS_FONT_MAP
    function decodeBossFontText(text: string): string {
        let result = text;
        // Replace PUA chars by scanning the string
        for (let i = 0; i < result.length; i++) {
            const mapped = BOSS_FONT_MAP[result[i]];
            if (mapped) {
                result = result.replace(new RegExp(result[i], 'g'), mapped);
            }
        }
        return result;
    }

    function parseBossJobCard(card: HTMLElement, anchor: HTMLAnchorElement): any {
        const title = cleanText(anchor.innerText).slice(0, 60);
        const url = anchor.href.split('?')[0];

        // Salary — decode all font chars in card HTML, then extract
        let salary = '面议';
        const cardHtml = card.innerHTML;
        // Decode &#x hex entities if any
        let decodedHtml = cardHtml.replace(/&#x([0-9a-fA-F]+);/g, (_m, hex) => {
            const ch = String.fromCharCode(parseInt(hex, 16));
            return BOSS_FONT_MAP[ch] || _m;
        });
        // Decode raw PUA chars
        decodedHtml = decodeBossFontText(decodedHtml);
        // Parse back to text
        const tmp = document.createElement('div');
        tmp.innerHTML = decodedHtml;
        const decodedText = cleanText(tmp.textContent || '');
        const salaryMatch = decodedText.match(/(\d+)\s*[-~至]\s*(\d+)\s*K(?:\s*[·•]\s*\d+薪)?|(\d+)\s*K|(\d+-\d+)\s*元\/天|面议/);
        salary = salaryMatch ? salaryMatch[0].replace(/\s+/g, '') : '面议';

        // Company — BOSS uses /gongsi/ not /company/
        const companyEl = card.querySelector("a[href*='/gongsi/'], a[href*='/company/']") as HTMLElement | null;
        const companyHref = (companyEl as HTMLAnchorElement)?.href || '';
        const company = cleanText(companyEl?.textContent || '').slice(0, 80) || '未知';

        // Area — prefer structured selectors, avoid broad [class*="area"] matches
        const areaEl = card.querySelector('.job-area, .area-link, [class*="job-area"], [class*="jobArea"], [class*="work-area"]') as HTMLElement | null;
        let area = cleanText(areaEl?.textContent || areaEl?.innerText || '');
        if (!area || area.length > 40) {
            // fallback: search for city name in card text
            const cardText = cleanText(card.innerText);
            for (const city of cityNames) {
                const idx = cardText.indexOf(city);
                if (idx >= 0) {
                    area = cardText.slice(idx, idx + 20).split(/[\n\r]/)[0].trim();
                    break;
                }
            }
        }
        if (!area) area = '未知';

        const tags = Array.from(card.querySelectorAll('[class*="tag"], [class*="Tag"], [class*="label"], [class*="Label"]'))
            .map(el => cleanText((el as HTMLElement).innerText))
            .filter(Boolean)
            .filter(t => t.length <= 24);

        return { title, url, salary, company, companyUrl: companyHref, area, skills: tags };
    }

    async function scanAndHarvestBoss(overlay?: HTMLElement) {
        const jobLinks = document.querySelectorAll("a[href*='/job_detail/']");
        jobLinks.forEach(link => {
            try {
                const anchor = link as HTMLAnchorElement;
                const fullUrl = anchor.href.split('?')[0];
                const title = cleanText(anchor.innerText);
                if (harvestedJobs.has(fullUrl)) return;
                if (title.length < 2) return;
                const card = findBossJobCard(anchor);
                if (card) {
                    const job = parseBossJobCard(card, anchor);
                    harvestedJobs.set(fullUrl, job);
                    if (overlay) overlay.innerText = `Joblens (${harvesterVersion})\n已捕获：${harvestedJobs.size} 个岗位...`;
                }
            } catch (e) {}
        });
    }

    function getBossNextPageUrl(): string | null {
        const nextBtn = document.querySelector('[class*="next"], .options-pages a:last-child, [title="下一页"]') as HTMLAnchorElement | null;
        if (!nextBtn || nextBtn.classList.contains('disabled') || nextBtn.getAttribute('aria-disabled') === 'true') return null;
        const href = nextBtn.getAttribute('href');
        if (!href) return null;
        return new URL(href, window.location.href).toString();
    }

    async function handleBossPagination(): Promise<boolean> {
        const nextUrl = getBossNextPageUrl();
        if (!nextUrl) return false;
        await new Promise(r => setTimeout(r, 5000));
        window.location.replace(nextUrl);
        return true;
    }

    // --- BOSS直聘 detail page parsing ---

    type BossDetailResult = {
        status: "success" | "failed";
        jobUrl: string;
        detailTitle?: string;
        detailTags?: string[];
        salary?: string;
        companyName?: string;
        workAddress?: string;
        descriptionText?: string;
        raw?: {
            detailText: string;
            detailHtml?: string;
            capturedAt: string;
        };
        error?: string;
    };

    function parseBossDetailPage(): BossDetailResult {
        try {
            if (isCaptchaPage()) {
                return { status: "failed", jobUrl: window.location.href.split("?")[0], error: "security verification page detected" };
            }
            if (isBossLoginWall()) {
                return { status: "failed", jobUrl: window.location.href.split("?")[0], error: "login required" };
            }

            const jobUrl = window.location.href.split("?")[0];

            // Scope queries to the main content area, not the similar-jobs sidebar
            const mainScope = document.querySelector('.job-box .job-detail, .job-banner, .smallbanner');

            const titleEl = document.querySelector('.job-banner h1, .info-primary h1') as HTMLElement | null;
            const title = cleanText(titleEl?.innerText);

            const salaryEl = document.querySelector('.job-banner .salary, .info-primary .salary, .detail-box .salary') as HTMLElement | null;
            let salary = '';
            if (salaryEl) {
                salary = decryptBossSalary(salaryEl) || extractBossSalaryFromText(cleanText(salaryEl.innerText));
            }

            // Company: prefer the sider-company link (always the correct company),
            // fall back to smallbanner info, never match similar-jobs sidebar
            let company = '';
            let companyEl = document.querySelector('.sider-company .company-info a, .sider-company [class*="company-name"]') as HTMLElement | null;
            if (!companyEl || !cleanText(companyEl.innerText)) {
                companyEl = document.querySelector('.smallbanner .detail-op .info') as HTMLElement | null;
            }
            if (companyEl) {
                const text = cleanText(companyEl.textContent || companyEl.innerText);
                // Extract company name from text like "上海寻梦\n查看所有职位\n..."
                company = text.split(/[\n\r]/)[0].trim().slice(0, 80);
            }

            const tagEls = mainScope ? mainScope.querySelectorAll('[class*="job-keyword"], [class*="jobKeyword"], [class*="tag-item"]') : [];
            const tags = Array.from(tagEls).map(el => cleanText((el as HTMLElement).innerText)).filter(Boolean);

            const descEl = document.querySelector('.job-detail .job-sec-text, .job-detail [class*="jobSecText"], .job-detail [class*="detail-text"]') as HTMLElement | null;
            const description = cleanText(descEl?.innerText || document.body.innerText);

            const addrEl = document.querySelector('.job-detail .location-address, .job-detail [class*="job-address"], .job-detail [class*="jobAddress"]') as HTMLElement | null;
            const address = cleanText(addrEl?.innerText);

            return {
                status: "success", jobUrl,
                detailTitle: title, detailTags: tags, salary,
                companyName: company, workAddress: address,
                descriptionText: description,
                raw: {
                    detailText: document.body.innerText,
                    detailHtml: document.documentElement.outerHTML,
                    capturedAt: new Date().toISOString(),
                }
            };
        } catch (error) {
            return { status: "failed", jobUrl: window.location.href.split("?")[0], error: error instanceof Error ? error.message : String(error) };
        }
    }

    // --- BOSS直聘 export helpers ---

    async function triggerBossFinalSave(isAuto: boolean, overlay?: HTMLElement) {
        await scanAndHarvestBoss(overlay);
        const keyword = getKeywordFromPage();
        const now = new Date();
        const timestamp = now.getFullYear().toString() + (now.getMonth() + 1).toString().padStart(2, '0') + now.getDate().toString().padStart(2, '0') + '_' + now.getHours().toString().padStart(2, '0') + now.getMinutes().toString().padStart(2, '0') + now.getSeconds().toString().padStart(2, '0');
        const fileName = isHarvestTestMode() ? `BOSS_TEST_${keyword}_${timestamp}.md` : `BOSS_${keyword}_${timestamp}.md`;
        const jobs = Array.from(harvestedJobs.values());
        let content = `# BOSS直聘岗位收割：${keyword}\n\n- 数量：${jobs.length}\n- 时间：${new Date().toLocaleString()}\n\n## 岗位列表\n\n`;
        jobs.forEach((r, idx) => {
            content += `### ${idx + 1}. ${r.title}\n- 公司：${r.company || '未知'}\n- 薪资：**${r.salary}**\n- 地点：${r.area || '未知'}\n- 链接：[查看详情](${r.url})\n\n`;
        });
        const response = await downloadTextFile(fileName, content, "text/markdown", isAuto);
        if (response?.success && isAuto && overlay) { overlay.style.background = "green"; overlay.innerText = "✅ BOSS采集完成"; }
        if (isAuto && isListQueueMode()) {
            await chrome.runtime.sendMessage({ action: "bossListHarvestDone", success: Boolean(response?.success), keyword, fileName });
            await chrome.runtime.sendMessage({ action: "closeCurrentTab" });
        }
    }

    async function exportBossDirectJobDetailResult(overlay: HTMLElement) {
        const now = new Date();
        const timestamp = now.getFullYear().toString() + (now.getMonth() + 1).toString().padStart(2, '0') + now.getDate().toString().padStart(2, '0') + '_' + now.getHours().toString().padStart(2, '0') + now.getMinutes().toString().padStart(2, '0') + now.getSeconds().toString().padStart(2, '0');
        const keyword = getDirectJobDetailKeyword();
        const detail = parseBossDetailPage();
        const job = {
            title: detail.detailTitle || document.title || "未知岗位",
            company: detail.companyName || "未知公司",
            companyUrl: window.location.origin,
            area: detail.workAddress || "未知",
            salary: detail.salary || "未知",
            exp: "未知", edu: "未知",
            url: detail.jobUrl || window.location.href.split("?")[0]
        };
        const metadata = { platform: "boss", keyword, url: window.location.href, collectedAt: now.toISOString(), mode: "job_detail", harvesterVersion };
        const companyName = sanitizeArtifactNamePart(job.company, "unknown_company");
        const jobTitle = sanitizeArtifactNamePart(job.title, "unknown_job");
        const markdownFileName = `BOSS_DETAIL_${companyName}_${jobTitle}_${timestamp}.md`;

        const markdownResp = await downloadTextFile(markdownFileName, createBossDetailMarkdown(job, detail, metadata), "text/markdown", true);

        if (!markdownResp?.success || detail.status === "failed") {
            if (isCaptchaPage()) {
                overlay.style.background = "red";
                overlay.innerText = `⚠️ 验证码拦截！\n请手动完成人机验证`;
                chrome.runtime.sendMessage({ action: "captchaDetected" }).catch(() => {});
                return;
            }
            if (isBossLoginWall()) {
                overlay.style.background = "red";
                overlay.innerText = `⚠️ 需要登录BOSS直聘\n请在浏览器中登录后重试\n登录后刷新页面即可继续采集`;
                chrome.runtime.sendMessage({ action: "bossLoginRequired" }).catch(() => {});
                return;
            }
        }

        if (markdownResp?.success) {
            overlay.style.background = "green";
            overlay.innerText = `✅ BOSS详情采集完成\n${job.company}\n${job.title}`;
        } else {
            overlay.style.background = "#9a3412";
            overlay.innerText = `详情文件下载失败：${markdownResp?.error || "未知错误"}`;
        }
        setTimeout(() => { chrome.runtime.sendMessage({ action: "closeCurrentTab" }).catch(() => { window.close(); }); }, 1500);
    }

    function createBossDetailMarkdown(job: any, detail: BossDetailResult, metadata: any): string {
        let content = `---\nsource: boss\nkeyword: ${metadata.keyword}\ncompany: ${job.company}\ntitle: ${job.title}\nurl: ${job.url}\ncollected: ${metadata.collectedAt}\n---\n\n`;
        content += `# ${job.company}_${job.title}\n\n`;
        content += `- 来源：BOSS直聘\n- 状态：详情页采集\n- 公司：${job.company}\n- 地点：${job.area || "未知"}\n- 薪资：${job.salary || "未知"}\n- 岗位链接：[查看详情](${job.url})\n- 采集URL：${window.location.href}\n- 时间：${new Date().toLocaleString()}\n\n`;
        content += `## 详情字段\n\n- 详情状态：${detail.status}\n`;
        if (detail.status === "failed") {
            content += `- 失败原因：${detail.error || "未知"}\n`;
            return content;
        }
        content += `- 详情标题：${detail.detailTitle || "未知"}\n- 详情薪资：${detail.salary || "未知"}\n- 详情公司：${detail.companyName || "未知"}\n- 详情地址：${detail.workAddress || "未知"}\n\n`;
        content += `## 详情岗位标签\n\n${detail.detailTags?.length ? detail.detailTags.map(tag => `- ${tag}`).join("\n") : "- 未提供"}\n\n`;
        content += `## 职位详情全文\n\n${detail.descriptionText || "未知"}\n\n`;
        return content;
    }

    // Main entry point logic...
    if (isKeywordDiscoveryMode()) {
        const overlay = document.createElement('div');
        overlay.style.cssText = 'position:fixed;top:10px;right:10px;background:#2563eb;color:white;padding:20px;z-index:999999;font-weight:bold;border-radius:10px;';
        document.body.appendChild(overlay);
        setTimeout(async () => {
            const groups = isZhilianPage
                ? await discoverZhilianKeywords(overlay)
                : await discoverBossKeywords(overlay);
            await exportKeywordDiscoveryResult(groups, overlay);
        }, 2500);
    }

    if (isDirectJobDetailMode()) {
        const overlay = document.createElement('div');
        overlay.style.cssText = 'position:fixed;top:10px;right:10px;background:#7c3aed;color:white;padding:20px;z-index:999999;font-weight:bold;border-radius:10px;';
        document.body.appendChild(overlay);
        if (isZhilianPage) {
            setTimeout(() => exportDirectJobDetailResult(overlay), 1800);
        } else if (isBossPage) {
            setTimeout(() => exportBossDirectJobDetailResult(overlay), 3500);
        }
    }

    const isAuto = window.location.href.includes('joblens_auto=1') && !isKeywordDiscoveryMode() && !isDirectJobDetailMode();
    if (isAuto) {
        const overlay = document.createElement('div');
        overlay.style.cssText = 'position:fixed;top:10px;right:10px;background:red;color:white;padding:20px;z-index:999999;font-weight:bold;border-radius:10px;';
        document.body.appendChild(overlay);
        setTimeout(async () => {
            if (isZhilianPage) {
                await autoScroll(true, overlay);
                await triggerFinalSave(true, overlay);
                const isBatch = isKeywordBatchMode();
                if (isBatch) await advanceKeywordBatch(overlay);
            } else if (isBossPage) {
                await scanAndHarvestBoss(overlay);
                await triggerBossFinalSave(true, overlay);
                const hasNext = await handleBossPagination();
                if (!hasNext && overlay) {
                    // pagination exhausted — already saved by triggerBossFinalSave
                }
            }
        }, 3000);
    }

    chrome.runtime.onMessage.addListener((request, sender, sendResponse) => {
        if (window.joblensGeneration !== myGeneration) return;
        if (request.action === "ping") { sendResponse({ success: true }); return true; }
        if (request.action === "parseZhilianDetail") { sendResponse(parseZhilianDetailPage()); return true; }
        if (request.action === "parseBossDetail") { sendResponse(parseBossDetailPage()); return true; }
        return true;
    });
})();
