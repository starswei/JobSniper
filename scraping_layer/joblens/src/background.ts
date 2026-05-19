/**
 * Joblens - Background Service Worker
 *
 * Handles the background queue for recruitment data harvesting.
 * Communicates with the local filesystem via JSONL task/result files in the Downloads directory.
 */

const DETAIL_TASK_FILE = 'file:///D:/Downloads/zhilian_detail_tasks.jsonl';
const DETAIL_RESULTS_FILE = 'zhilian_detail_results.jsonl';
const DETAIL_DONE_LOCKS_KEY = 'joblens_detail_done_locks_v1';
const DETAIL_INFLIGHT_LOCKS_KEY = 'joblens_detail_inflight_locks_v1';
const DETAIL_INFLIGHT_TTL_MS = 10 * 60 * 1000;
const DETAIL_QUEUE_PAUSED_KEY = 'joblens_detail_queue_paused_v1';

const LIST_TASK_FILE = 'file:///D:/Downloads/zhilian_list_tasks.jsonl';
const LIST_RESULTS_FILE = 'zhilian_list_results.jsonl';
const LIST_DONE_LOCKS_KEY = 'joblens_list_done_locks_v1';
const LIST_INFLIGHT_LOCKS_KEY = 'joblens_list_inflight_locks_v1';
const LIST_INFLIGHT_TTL_MS = 30 * 60 * 1000;

const BOSS_DETAIL_TASK_FILE = 'file:///D:/Downloads/boss_detail_tasks.jsonl';
const BOSS_DETAIL_RESULTS_FILE = 'boss_detail_results.jsonl';
const BOSS_DETAIL_DONE_LOCKS_KEY = 'joblens_boss_detail_done_locks_v1';
const BOSS_DETAIL_INFLIGHT_LOCKS_KEY = 'joblens_boss_detail_inflight_locks_v1';
const BOSS_DETAIL_INFLIGHT_TTL_MS = 10 * 60 * 1000;
const BOSS_DETAIL_QUEUE_PAUSED_KEY = 'joblens_boss_detail_queue_paused_v1';

const BOSS_LIST_TASK_FILE = 'file:///D:/Downloads/boss_list_tasks.jsonl';
const BOSS_LIST_RESULTS_FILE = 'boss_list_results.jsonl';
const BOSS_LIST_DONE_LOCKS_KEY = 'joblens_boss_list_done_locks_v1';
const BOSS_LIST_INFLIGHT_LOCKS_KEY = 'joblens_boss_list_inflight_locks_v1';
const BOSS_LIST_INFLIGHT_TTL_MS = 30 * 60 * 1000;

type DetailTask = {
	index: number;
	url: string;
	keyword?: string;
	jobId?: string;
};

type ListTask = {
	index: number;
	url: string;
	keyword?: string;
	taskId?: string;
};

type QueuePauseState = {
	paused: boolean;
	reason?: string;
	paused_at?: string;
	tab_id?: number;
};

type DetailProcessResult = {
	success: boolean;
	reason?: string;
};

type ListProcessResult = {
	success: boolean;
	reason?: string;
	fileName?: string;
};

type RuntimeRequest = {
	action?: string;
	tabId?: number;
	dataUrl?: string;
	content?: string;
	mimeType?: string;
	fileName?: string;
	jobs?: Array<{ index: number; title: string; url: string }>;
	debug?: boolean;
	success?: boolean;
	error?: string;
};

let isDetailQueueRunning = false;
let isListQueueRunning = false;

const detailRuntimeClaims = new Set<string>();
const listRuntimeClaims = new Set<string>();
const captchaResolvers = new Map<number, (result: DetailProcessResult) => void>();
const listHarvestResolvers = new Map<number, (result: ListProcessResult) => void>();

let isBossDetailQueueRunning = false;
let isBossListQueueRunning = false;

const bossDetailRuntimeClaims = new Set<string>();
const bossListRuntimeClaims = new Set<string>();
const bossCaptchaResolvers = new Map<number, (result: DetailProcessResult) => void>();
const bossListHarvestResolvers = new Map<number, (result: ListProcessResult) => void>();
	const bossLoginRequiredResolvers = new Map<number, (result: DetailProcessResult) => void>();

function sleep(ms: number): Promise<void> {
	return new Promise(resolve => setTimeout(resolve, ms));
}

function sanitizeDownloadFileName(fileName: string): string {
	const sanitized = fileName
		.replace(/[\/\\?%*:|"<>]/g, '-')
		.replace(/[\x00-\x1f\x80-\x9f]/g, '')
		.trim();
	return sanitized || 'job_export.md';
}

function isValidPageUrl(url: string | undefined): boolean {
	if (!url) return false;
	return /^https?:\/\//i.test(url);
}

function normalizeZhilianDetailUrl(url: string): string {
	try {
		const parsed = new URL(url);
		parsed.protocol = 'https:';
		parsed.hash = '';
		parsed.search = '';
		return parsed.toString();
	} catch {
		return url.split('#')[0].split('?')[0].replace(/^http:/, 'https:');
	}
}

function getZhilianDetailJobId(url: string): string | undefined {
	const match = normalizeZhilianDetailUrl(url).match(/\/jobdetail\/([^/?#]+)\.htm/i);
	return match?.[1];
}

function normalizeZhilianListUrl(url: string): string {
	try {
		const parsed = new URL(url);
		parsed.protocol = 'https:';
		parsed.hash = '';
		return parsed.toString();
	} catch {
		return url.split('#')[0].replace(/^http:/, 'https:');
	}
}

function getDetailTaskLockKey(task: Pick<DetailTask, 'url' | 'jobId'>): string {
	const jobId = task.jobId || getZhilianDetailJobId(task.url);
	return jobId ? `job:${jobId}` : `url:${normalizeZhilianDetailUrl(task.url)}`;
}

function getListTaskLockKey(task: Pick<ListTask, 'url' | 'taskId'>): string {
	return task.taskId ? `task:${task.taskId}` : `url:${normalizeZhilianListUrl(task.url)}`;
}

function normalizeBossDetailUrl(url: string): string {
	try {
		const parsed = new URL(url);
		parsed.protocol = 'https:';
		parsed.hash = '';
		parsed.search = '';
		return parsed.toString();
	} catch {
		return url.split('#')[0].split('?')[0].replace(/^http:/, 'https:');
	}
}

function getBossDetailJobId(url: string): string | undefined {
	const match = normalizeBossDetailUrl(url).match(/\/job_detail\/([^/?#]+)\.html/i);
	return match?.[1];
}

function normalizeBossListUrl(url: string): string {
	try {
		const parsed = new URL(url);
		parsed.protocol = 'https:';
		parsed.hash = '';
		return parsed.toString();
	} catch {
		return url.split('#')[0].replace(/^http:/, 'https:');
	}
}

function getBossDetailTaskLockKey(task: Pick<DetailTask, 'url' | 'jobId'>): string {
	const jobId = task.jobId || getBossDetailJobId(task.url);
	return jobId ? `boss_job:${jobId}` : `boss_url:${normalizeBossDetailUrl(task.url)}`;
}

function getBossListTaskLockKey(task: Pick<ListTask, 'url' | 'taskId'>): string {
	return task.taskId ? `boss_task:${task.taskId}` : `boss_url:${normalizeBossListUrl(task.url)}`;
}

async function readBossDetailQueuePauseState(): Promise<QueuePauseState> {
	try {
		const data = await chrome.storage.local.get(BOSS_DETAIL_QUEUE_PAUSED_KEY);
		const value = data[BOSS_DETAIL_QUEUE_PAUSED_KEY];
		if (value && typeof value === 'object') {
			const v = value as Record<string, unknown>;
			return {
				paused: Boolean(v.paused),
				reason: typeof v.reason === 'string' ? v.reason : undefined,
				paused_at: typeof v.paused_at === 'string' ? v.paused_at : undefined,
				tab_id: typeof v.tab_id === 'number' ? v.tab_id : undefined
			};
		}
	} catch {}
	return { paused: false };
}

async function setBossDetailQueuePaused(paused: boolean, reason?: string, tabId?: number): Promise<void> {
	try {
		if (paused) {
			await chrome.storage.local.set({
				[BOSS_DETAIL_QUEUE_PAUSED_KEY]: { paused: true, reason, paused_at: new Date().toISOString(), tab_id: tabId }
			});
			try { await chrome.action.setBadgeBackgroundColor({ color: '#b91c1c' }); } catch {}
			try { await chrome.action.setBadgeText({ text: 'CAP' }); } catch {}
			try { await chrome.alarms.clear('bossDetailQueuePoll'); } catch {}
			return;
		}
		await chrome.storage.local.set({ [BOSS_DETAIL_QUEUE_PAUSED_KEY]: { paused: false, resumed_at: new Date().toISOString() } });
		try { await chrome.action.setBadgeText({ text: '' }); } catch {}
		try { chrome.alarms.create('bossDetailQueuePoll', { periodInMinutes: 5 / 60 }); } catch {}
	} catch {}
}

async function injectContentScript(tabId: number): Promise<void> {
	await chrome.scripting.executeScript({
		target: { tabId },
		files: ['content.js']
	});

	for (let i = 0; i < 8; i++) {
		try {
			await chrome.tabs.sendMessage(tabId, { action: 'ping' });
			return;
		} catch {
			await sleep(50);
		}
	}
	throw new Error('Content script did not respond after injection');
}

async function ensureContentScriptLoadedInBackground(tabId: number): Promise<void> {
	const tab = await chrome.tabs.get(tabId);
	if (!isValidPageUrl(tab.url)) {
		throw new Error('Invalid URL for content script injection');
	}

	try {
		await chrome.tabs.sendMessage(tabId, { action: 'ping' });
	} catch {
		await injectContentScript(tabId);
	}
}

async function waitForTabComplete(tabId: number, timeoutMs = 15000): Promise<void> {
	const startedAt = Date.now();
	while (Date.now() - startedAt < timeoutMs) {
		const tab = await chrome.tabs.get(tabId);
		if (tab.status === 'complete') {
			await sleep(1200);
			return;
		}
		await sleep(500);
	}
	throw new Error('Timed out waiting for tab to load');
}

async function readDetailQueuePauseState(): Promise<QueuePauseState> {
	try {
		const data = await chrome.storage.local.get(DETAIL_QUEUE_PAUSED_KEY);
		const value = data[DETAIL_QUEUE_PAUSED_KEY];
		if (value && typeof value === 'object') {
			const v = value as Record<string, unknown>;
			return {
				paused: Boolean(v.paused),
				reason: typeof v.reason === 'string' ? v.reason : undefined,
				paused_at: typeof v.paused_at === 'string' ? v.paused_at : undefined,
				tab_id: typeof v.tab_id === 'number' ? v.tab_id : undefined
			};
		}
	} catch {}
	return { paused: false };
}

async function setDetailQueuePaused(paused: boolean, reason?: string, tabId?: number): Promise<void> {
	try {
		if (paused) {
			await chrome.storage.local.set({
				[DETAIL_QUEUE_PAUSED_KEY]: {
					paused: true,
					reason,
					paused_at: new Date().toISOString(),
					tab_id: tabId
				}
			});
			try { await chrome.action.setBadgeBackgroundColor({ color: '#b91c1c' }); } catch {}
			try { await chrome.action.setBadgeText({ text: 'CAP' }); } catch {}
			try { await chrome.alarms.clear('detailQueuePoll'); } catch {}
			return;
		}

		await chrome.storage.local.set({
			[DETAIL_QUEUE_PAUSED_KEY]: {
				paused: false,
				resumed_at: new Date().toISOString()
			}
		});
		try { await chrome.action.setBadgeText({ text: '' }); } catch {}
		try { chrome.alarms.create('detailQueuePoll', { periodInMinutes: 5 / 60 }); } catch {}
	} catch {}
}

async function readLockMap(key: string): Promise<Record<string, number>> {
	try {
		const data = await chrome.storage.local.get(key);
		const value = data[key];
		return value && typeof value === 'object' ? value as Record<string, number> : {};
	} catch {
		return {};
	}
}

async function writeLockMap(key: string, value: Record<string, number>): Promise<void> {
	try {
		await chrome.storage.local.set({ [key]: value });
	} catch {}
}

async function readActiveInflightLocks(key: string, ttlMs: number, now: number): Promise<Record<string, number>> {
	const inflight = await readLockMap(key);
	let changed = false;
	for (const [lockKey, claimedAt] of Object.entries(inflight)) {
		if (!Number.isFinite(claimedAt) || now - claimedAt > ttlMs) {
			delete inflight[lockKey];
			changed = true;
		}
	}
	if (changed) await writeLockMap(key, inflight);
	return inflight;
}

async function claimTask(
	lockKey: string,
	runtimeClaims: Set<string>,
	doneKey: string,
	inflightKey: string,
	inflightTtlMs: number
): Promise<boolean> {
	if (runtimeClaims.has(lockKey)) return false;
	runtimeClaims.add(lockKey);

	const now = Date.now();
	const done = await readLockMap(doneKey);
	if (done[lockKey]) {
		runtimeClaims.delete(lockKey);
		return false;
	}

	const inflight = await readActiveInflightLocks(inflightKey, inflightTtlMs, now);
	if (inflight[lockKey]) {
		runtimeClaims.delete(lockKey);
		return false;
	}

	inflight[lockKey] = now;
	await writeLockMap(inflightKey, inflight);
	return true;
}

async function completeTask(
	lockKey: string,
	success: boolean,
	runtimeClaims: Set<string>,
	doneKey: string,
	inflightKey: string
): Promise<void> {
	runtimeClaims.delete(lockKey);

	const inflight = await readLockMap(inflightKey);
	delete inflight[lockKey];
	await writeLockMap(inflightKey, inflight);

	if (success) {
		const done = await readLockMap(doneKey);
		done[lockKey] = Date.now();
		await writeLockMap(doneKey, done);
	}
}

async function fetchDetailTasks(): Promise<DetailTask[]> {
	try {
		const resp = await fetch(DETAIL_TASK_FILE);
		if (!resp.ok) return [];
		const text = await resp.text();
		const tasks: DetailTask[] = [];
		text.split('\n').forEach((rawLine, index) => {
			const line = rawLine.trim();
			if (!line) return;
			try {
				const task = JSON.parse(line);
				if (!task?.url) return;
				tasks.push({
					index,
					url: task.url,
					keyword: task.keyword,
					jobId: task.job_id || getZhilianDetailJobId(task.url)
				});
			} catch {}
		});
		return tasks;
	} catch {
		return [];
	}
}

async function fetchListTasks(): Promise<ListTask[]> {
	try {
		const resp = await fetch(LIST_TASK_FILE);
		if (!resp.ok) return [];
		const text = await resp.text();
		const tasks: ListTask[] = [];
		text.split('\n').forEach((rawLine, index) => {
			const line = rawLine.trim();
			if (!line) return;
			try {
				const task = JSON.parse(line);
				if (!task?.url) return;
				tasks.push({
					index,
					url: task.url,
					keyword: task.keyword,
					taskId: task.task_id || task.taskId
				});
			} catch {}
		});
		return tasks;
	} catch {
		return [];
	}
}

async function readJsonlResults(fileName: string): Promise<any[]> {
	try {
		const resp = await fetch(`file:///D:/Downloads/${fileName}`);
		if (!resp.ok) return [];
		const text = await resp.text();
		return text.split('\n')
			.filter((line: string) => line.trim())
			.map((line: string) => {
				try {
					return JSON.parse(line);
				} catch {
					return null;
				}
			})
			.filter((record: any) => record !== null);
	} catch {
		return [];
	}
}

async function writeJsonlResults(fileName: string, records: any[]): Promise<void> {
	const content = records.map((record: any) => JSON.stringify(record)).join('\n') + '\n';
	await chrome.downloads.download({
		url: `data:application/x-ndjson;charset=utf-8,${encodeURIComponent(content)}`,
		filename: fileName,
		conflictAction: 'overwrite',
		saveAs: false
	});
}

async function writeDetailResult(task: DetailTask, status: string, error?: string): Promise<void> {
	try {
		const record: any = {
			task_index: task.index,
			url: task.url,
			normalized_url: normalizeZhilianDetailUrl(task.url),
			job_id: task.jobId || getZhilianDetailJobId(task.url),
			keyword: task.keyword,
			status,
			recorded_at: new Date().toISOString()
		};
		if (error) record.error = error;

		const existing = await readJsonlResults(DETAIL_RESULTS_FILE);
		existing.push(record);
		await writeJsonlResults(DETAIL_RESULTS_FILE, existing);
	} catch {}
}

async function writeListResult(task: ListTask, status: string, error?: string, fileName?: string): Promise<void> {
	try {
		const record: any = {
			task_index: task.index,
			task_id: task.taskId,
			url: task.url,
			normalized_url: normalizeZhilianListUrl(task.url),
			keyword: task.keyword,
			status,
			recorded_at: new Date().toISOString()
		};
		if (fileName) record.file_name = fileName;
		if (error) record.error = error;

		const existing = await readJsonlResults(LIST_RESULTS_FILE);
		existing.push(record);
		await writeJsonlResults(LIST_RESULTS_FILE, existing);
	} catch {}
}

async function processSingleDetailUrl(url: string): Promise<DetailProcessResult> {
	let tabId: number | undefined;
	let timedOut = false;
	let resolvedResult: DetailProcessResult | undefined;

	try {
		const tab = await chrome.tabs.create({ url, active: false });
		tabId = tab.id;
		if (!tabId) return { success: false, reason: 'no tab id' };

		await new Promise<void>((resolve) => {
			const cleanup = () => {
				chrome.tabs.onRemoved.removeListener(handleRemoved);
				clearTimeout(timer);
				if (tabId) captchaResolvers.delete(tabId);
			};
			const handleRemoved = (removedId: number) => {
				if (removedId !== tabId) return;
				cleanup();
				if (!resolvedResult) resolvedResult = { success: true };
				resolve();
			};
			const timer = setTimeout(() => {
				timedOut = true;
				cleanup();
				resolve();
			}, 60000);

			chrome.tabs.onRemoved.addListener(handleRemoved);
			captchaResolvers.set(tabId!, (result: DetailProcessResult) => {
				cleanup();
				resolvedResult = result;
				resolve();
			});
		});

		if (resolvedResult) return resolvedResult;
		if (timedOut) return { success: false, reason: 'timeout (60s)' };
		return { success: true };
	} catch (error) {
		if (tabId) {
			try { await chrome.tabs.remove(tabId); } catch {}
		}
		return { success: false, reason: error instanceof Error ? error.message : 'exception' };
	}
}

async function waitForListHarvestOrTimeout(tabId: number, timeoutMs = 10 * 60 * 1000): Promise<ListProcessResult> {
	let timedOut = false;
	let resolvedResult: ListProcessResult | undefined;

	await new Promise<void>((resolve) => {
		const cleanup = () => {
			chrome.tabs.onRemoved.removeListener(handleRemoved);
			clearTimeout(timer);
			listHarvestResolvers.delete(tabId);
		};
		const handleRemoved = (removedId: number) => {
			if (removedId !== tabId) return;
			cleanup();
			if (!resolvedResult) resolvedResult = { success: false, reason: 'tab closed' };
			resolve();
		};
		const timer = setTimeout(() => {
			timedOut = true;
			cleanup();
			resolve();
		}, timeoutMs);

		chrome.tabs.onRemoved.addListener(handleRemoved);
		listHarvestResolvers.set(tabId, (result: ListProcessResult) => {
			cleanup();
			resolvedResult = result;
			resolve();
		});
	});

	if (resolvedResult) return resolvedResult;
	if (timedOut) return { success: false, reason: `timeout (${Math.floor(timeoutMs / 1000)}s)` };
	return { success: false, reason: 'unknown' };
}

async function processSingleListUrl(url: string): Promise<ListProcessResult> {
	let tabId: number | undefined;
	try {
		const tab = await chrome.tabs.create({ url, active: false });
		tabId = tab.id;
		if (!tabId) return { success: false, reason: 'no tab id' };

		await waitForTabComplete(tabId, 30000);
		await ensureContentScriptLoadedInBackground(tabId);
		return await waitForListHarvestOrTimeout(tabId);
	} catch (error) {
		return { success: false, reason: error instanceof Error ? error.message : String(error) };
	} finally {
		if (tabId) {
			try { await chrome.tabs.remove(tabId); } catch {}
		}
	}
}

async function processSingleBossDetailUrl(url: string): Promise<DetailProcessResult> {
	let tabId: number | undefined;
	let timedOut = false;
	let resolvedResult: DetailProcessResult | undefined;

	try {
		const tab = await chrome.tabs.create({ url, active: false });
		tabId = tab.id;
		if (!tabId) return { success: false, reason: 'no tab id' };

		await new Promise<void>((resolve) => {
			const cleanup = () => {
				chrome.tabs.onRemoved.removeListener(handleRemoved);
				clearTimeout(timer);
				if (tabId) bossCaptchaResolvers.delete(tabId);
				if (tabId) bossLoginRequiredResolvers.delete(tabId);
			};
			const handleRemoved = (removedId: number) => {
				if (removedId !== tabId) return;
				cleanup();
				if (!resolvedResult) resolvedResult = { success: true };
				resolve();
			};
			const timer = setTimeout(() => {
				timedOut = true;
				cleanup();
				resolve();
			}, 120000); // 120s for detail+company collection

			chrome.tabs.onRemoved.addListener(handleRemoved);
			bossCaptchaResolvers.set(tabId!, (result: DetailProcessResult) => {
				cleanup();
				resolvedResult = result;
				resolve();
			});
			bossLoginRequiredResolvers.set(tabId!, (result: DetailProcessResult) => {
				cleanup();
				resolvedResult = result;
				resolve();
			});
		});

		if (resolvedResult) return resolvedResult;
		if (timedOut) return { success: false, reason: 'timeout (120s)' };
		return { success: true };
	} catch (error) {
		if (tabId) {
			try { await chrome.tabs.remove(tabId); } catch {}
		}
		return { success: false, reason: error instanceof Error ? error.message : 'exception' };
	}
}

async function waitForBossListHarvestOrTimeout(tabId: number, timeoutMs = 10 * 60 * 1000): Promise<ListProcessResult> {
	let timedOut = false;
	let resolvedResult: ListProcessResult | undefined;

	await new Promise<void>((resolve) => {
		const cleanup = () => {
			chrome.tabs.onRemoved.removeListener(handleRemoved);
			clearTimeout(timer);
			bossListHarvestResolvers.delete(tabId);
		};
		const handleRemoved = (removedId: number) => {
			if (removedId !== tabId) return;
			cleanup();
			if (!resolvedResult) resolvedResult = { success: false, reason: 'tab closed' };
			resolve();
		};
		const timer = setTimeout(() => {
			timedOut = true;
			cleanup();
			resolve();
		}, timeoutMs);

		chrome.tabs.onRemoved.addListener(handleRemoved);
		bossListHarvestResolvers.set(tabId, (result: ListProcessResult) => {
			cleanup();
			resolvedResult = result;
			resolve();
		});
	});

	if (resolvedResult) return resolvedResult;
	if (timedOut) return { success: false, reason: `timeout (${Math.floor(timeoutMs / 1000)}s)` };
	return { success: false, reason: 'unknown' };
}

async function processSingleBossListUrl(url: string): Promise<ListProcessResult> {
	let tabId: number | undefined;
	try {
		const tab = await chrome.tabs.create({ url, active: false });
		tabId = tab.id;
		if (!tabId) return { success: false, reason: 'no tab id' };

		const result = await waitForBossListHarvestOrTimeout(tabId);
		return result;
	} catch (error) {
		if (tabId) {
			try { await chrome.tabs.remove(tabId); } catch {}
		}
		return { success: false, reason: error instanceof Error ? error.message : 'exception' };
	}
}
	
async function runDetailTaskQueue(): Promise<void> {
if (isDetailQueueRunning) return;
	isDetailQueueRunning = true;

	try {
		const pauseState = await readDetailQueuePauseState();
		if (pauseState.paused) {
			console.log('[Joblens] Detail queue paused:', pauseState.reason || 'paused');
			return;
		}

		const tasks = await fetchDetailTasks();
		if (tasks.length === 0) return;

		const results = await readJsonlResults(DETAIL_RESULTS_FILE);
		const doneUrls = new Set(
			results
				.filter((record: any) => record?.status === 'done' && record?.url)
				.map((record: any) => normalizeZhilianDetailUrl(record.url))
		);
		const doneJobIds = new Set(
			results
				.filter((record: any) => record?.status === 'done' && (record?.job_id || record?.url))
				.map((record: any) => record.job_id || getZhilianDetailJobId(record.url))
				.filter(Boolean)
		);
		const doneLocks = await readLockMap(DETAIL_DONE_LOCKS_KEY);
		const inflightLocks = await readActiveInflightLocks(DETAIL_INFLIGHT_LOCKS_KEY, DETAIL_INFLIGHT_TTL_MS, Date.now());
		const pendingTasks = tasks.filter(task => {
			const normalizedUrl = normalizeZhilianDetailUrl(task.url);
			const jobId = task.jobId || getZhilianDetailJobId(task.url);
			const lockKey = getDetailTaskLockKey(task);
			return !doneUrls.has(normalizedUrl)
				&& !(jobId && doneJobIds.has(jobId))
				&& !doneLocks[lockKey]
				&& !inflightLocks[lockKey];
		});

		if (pendingTasks.length === 0) return;

		console.log('[Joblens] Detail queue processing', pendingTasks.length, 'of', tasks.length, 'tasks');
		for (const task of pendingTasks) {
			const lockKey = getDetailTaskLockKey(task);
			const claimed = await claimTask(
				lockKey,
				detailRuntimeClaims,
				DETAIL_DONE_LOCKS_KEY,
				DETAIL_INFLIGHT_LOCKS_KEY,
				DETAIL_INFLIGHT_TTL_MS
			);
			if (!claimed) {
				console.log('[Joblens] Detail queue skip claimed task', task.index + 1, '/', tasks.length);
				continue;
			}

			console.log('[Joblens] Detail task', task.index + 1, '/', tasks.length);
			const result = await processSingleDetailUrl(task.url);
			await writeDetailResult(task, result.success ? 'done' : 'failed', result.reason);
			await completeTask(lockKey, result.success, detailRuntimeClaims, DETAIL_DONE_LOCKS_KEY, DETAIL_INFLIGHT_LOCKS_KEY);

			if (!result.success && result.reason === 'captcha detected') {
				await setDetailQueuePaused(true, 'captcha detected');
				break;
			}
			await sleep(2000);
		}
	} catch (error) {
		console.error('[Joblens] Detail queue error:', error);
	} finally {
		isDetailQueueRunning = false;
	}
}

async function runListTaskQueue(): Promise<void> {
	if (isListQueueRunning) return;
	isListQueueRunning = true;

	try {
		const tasks = await fetchListTasks();
		if (tasks.length === 0) return;

		const results = await readJsonlResults(LIST_RESULTS_FILE);
		const doneTaskIds = new Set(
			results
				.filter((record: any) => record?.status === 'done' && record?.task_id)
				.map((record: any) => String(record.task_id))
		);
		const doneUrls = new Set(
			results
				.filter((record: any) => record?.status === 'done' && record?.url)
				.map((record: any) => normalizeZhilianListUrl(record.url))
		);
		const doneLocks = await readLockMap(LIST_DONE_LOCKS_KEY);
		const inflightLocks = await readActiveInflightLocks(LIST_INFLIGHT_LOCKS_KEY, LIST_INFLIGHT_TTL_MS, Date.now());
		const pendingTasks = tasks.filter(task => {
			const lockKey = getListTaskLockKey(task);
			return !(task.taskId && doneTaskIds.has(String(task.taskId)))
				&& !doneUrls.has(normalizeZhilianListUrl(task.url))
				&& !doneLocks[lockKey]
				&& !inflightLocks[lockKey];
		});

		if (pendingTasks.length === 0) return;

		console.log('[Joblens] List queue processing', pendingTasks.length, 'of', tasks.length, 'tasks');
		for (const task of pendingTasks) {
			const lockKey = getListTaskLockKey(task);
			const claimed = await claimTask(
				lockKey,
				listRuntimeClaims,
				LIST_DONE_LOCKS_KEY,
				LIST_INFLIGHT_LOCKS_KEY,
				LIST_INFLIGHT_TTL_MS
			);
			if (!claimed) {
				console.log('[Joblens] List queue skip claimed task', task.index + 1, '/', tasks.length);
				continue;
			}

			console.log('[Joblens] List task', task.index + 1, '/', tasks.length);
			const result = await processSingleListUrl(task.url);
			await writeListResult(task, result.success ? 'done' : 'failed', result.reason, result.fileName);
			await completeTask(lockKey, result.success, listRuntimeClaims, LIST_DONE_LOCKS_KEY, LIST_INFLIGHT_LOCKS_KEY);
			await sleep(2000);
		}
	} catch (error) {
		console.error('[Joblens] List queue error:', error);
	} finally {
		isListQueueRunning = false;
	}
}

async function collectSingleZhilianDetail(job: { index: number; title: string; url: string }, debug: boolean): Promise<any> {
	let tabId: number | undefined;
	const requestedJobUrl = job.url.split('?')[0];

	try {
		const tab = await chrome.tabs.create({ url: job.url, active: false });
		tabId = tab.id;
		if (!tabId) throw new Error('Failed to create detail tab');

		await waitForTabComplete(tabId);
		await ensureContentScriptLoadedInBackground(tabId);
		const response = await chrome.tabs.sendMessage(tabId, { action: 'parseZhilianDetail' }) as any;
		if (debug) {
			console.log('[Joblens] Detail test parsed', {
				index: job.index,
				title: job.title,
				url: job.url,
				status: response?.status,
				error: response?.error
			});
		}

		return {
			index: job.index,
			title: job.title,
			...(response || {
				status: 'failed',
				error: 'Empty detail response'
			}),
			requestedJobUrl,
			finalUrl: response?.jobUrl,
			jobUrl: requestedJobUrl
		};
	} catch (error) {
		return {
			index: job.index,
			title: job.title,
			status: 'failed',
			jobUrl: requestedJobUrl,
			requestedJobUrl,
			error: error instanceof Error ? error.message : String(error)
		};
	} finally {
		if (tabId) {
			try { await chrome.tabs.remove(tabId); } catch {}
		}
	}
}

async function collectZhilianDetailTest(jobs: Array<{ index: number; title: string; url: string }>, debug: boolean): Promise<any[]> {
	const details: any[] = [];
	for (const job of jobs.slice(0, 5)) {
		details.push(await collectSingleZhilianDetail(job, debug));
		await sleep(700);
	}
	return details;
}

async function downloadFile(request: RuntimeRequest): Promise<{ success: boolean; downloadId?: number; fileName?: string; error?: string }> {
	const dataUrl = request.dataUrl;
	const content = request.content;
	const mimeType = request.mimeType || 'text/markdown';
	const fileName = sanitizeDownloadFileName(request.fileName || 'job_export.md');
	const downloadUrl = dataUrl || (
		typeof content === 'string'
			? `data:${mimeType};charset=utf-8,${encodeURIComponent(content)}`
			: ''
	);

	if (!downloadUrl) {
		return { success: false, error: 'Missing dataUrl or content for download' };
	}

	const downloadsApi = chrome.downloads;
	if (!downloadsApi?.download) {
		return { success: false, error: 'Downloads API is not available' };
	}

	return new Promise(resolve => {
		try {
			downloadsApi.download({
				url: downloadUrl,
				filename: fileName,
				conflictAction: 'uniquify',
				saveAs: false
			}, (downloadId?: number) => {
				const lastError = chrome.runtime?.lastError;
				if (lastError) {
					resolve({ success: false, error: lastError.message });
					return;
				}
				resolve({ success: true, downloadId, fileName });
			});
		} catch (error) {
			resolve({ success: false, error: error instanceof Error ? error.message : String(error) });
		}
	});
}

async function handleCaptchaDetected(sender: chrome.runtime.MessageSender): Promise<void> {
	const tabId = sender.tab?.id;
	if (!tabId) return;

	console.log('[Joblens] Captcha detected, bringing tab to foreground:', tabId);
	try { await chrome.tabs.update(tabId, { active: true }); } catch {}
	if (sender.tab?.windowId) {
		try { await chrome.windows.update(sender.tab.windowId, { focused: true }); } catch {}
	}

		const bossResolver = bossCaptchaResolvers.get(tabId);
		if (bossResolver) {
			await setBossDetailQueuePaused(true, 'captcha detected', tabId);
			bossResolver({ success: false, reason: 'captcha detected' });
			return;
		}

	await setDetailQueuePaused(true, 'captcha detected', tabId);
	const resolver = captchaResolvers.get(tabId);
	if (resolver) {
		resolver({ success: false, reason: 'captcha detected' });
	}
}

	async function handleBossLoginRequired(sender: chrome.runtime.MessageSender): Promise<void> {
		const tabId = sender.tab?.id;
		if (!tabId) return;
		console.log('[Joblens] BOSS login required, bringing tab to foreground:', tabId);
		try { await chrome.tabs.update(tabId, { active: true }); } catch {}
		if (sender.tab?.windowId) {
			try { await chrome.windows.update(sender.tab.windowId, { focused: true }); } catch {}
		}
		await setBossDetailQueuePaused(true, 'login required', tabId);
		const resolver = bossLoginRequiredResolvers.get(tabId);
		if (resolver) {
			resolver({ success: false, reason: 'login required' });
		}
	}

function handleRuntimeMessage(
	request: any,
	sender: chrome.runtime.MessageSender,
	sendResponse: (response?: any) => void
): boolean {
	if (typeof request !== 'object' || request === null) return false;

	const typedRequest = request as RuntimeRequest;
	switch (typedRequest.action) {
		case 'runDetailTaskQueue':
			setDetailQueuePaused(false)
				.then(() => runDetailTaskQueue())
				.then(() => sendResponse({ success: true }))
				.catch(error => sendResponse({ success: false, error: error instanceof Error ? error.message : String(error) }));
			return true;

		case 'runListTaskQueue':
			runListTaskQueue()
				.then(() => sendResponse({ success: true }))
				.catch(error => sendResponse({ success: false, error: error instanceof Error ? error.message : String(error) }));
			return true;

		case 'zhilianListHarvestDone': {
			const tabId = sender.tab?.id;
			const resolver = tabId ? listHarvestResolvers.get(tabId) : undefined;
			if (resolver) {
				resolver({
					success: Boolean(typedRequest.success),
					reason: typedRequest.error,
					fileName: typedRequest.fileName
				});
			}
			sendResponse({ success: true });
			return true;

		}
		case 'bossListHarvestDone': {
		const tabId = sender.tab?.id;
		const resolver = tabId ? bossListHarvestResolvers.get(tabId) : undefined;
		if (resolver) {
		resolver({
		success: Boolean(typedRequest.success),
		reason: typedRequest.error,
		fileName: typedRequest.fileName
		});
		}
		sendResponse({ success: true });
		return true;
		}

		case 'runBossDetailTaskQueue':
		setBossDetailQueuePaused(false)
		.then(() => runBossDetailTaskQueue())
		.then(() => sendResponse({ success: true }))
		.catch(error => sendResponse({ success: false, error: error instanceof Error ? error.message : String(error) }));
		return true;

		case 'runBossListTaskQueue':
		runBossListTaskQueue()
		.then(() => sendResponse({ success: true }))
		.catch(error => sendResponse({ success: false, error: error instanceof Error ? error.message : String(error) }));
		return true;

		case 'zhilianCollectDetailTest':
			if (!Array.isArray(typedRequest.jobs) || typedRequest.jobs.length === 0) {
				sendResponse({ success: false, error: 'Missing jobs for detail test' });
				return true;
			}
			collectZhilianDetailTest(typedRequest.jobs, Boolean(typedRequest.debug))
				.then(details => sendResponse({ success: true, details }))
				.catch(error => sendResponse({ success: false, error: error instanceof Error ? error.message : String(error) }));
			return true;

		case 'finalDownloadOnly':
			downloadFile(typedRequest)
				.then(sendResponse)
				.catch(error => sendResponse({ success: false, error: error instanceof Error ? error.message : String(error) }));
			return true;

		case 'closeCurrentTab': {
			const tabId = sender.tab?.id;
			if (!tabId) {
				sendResponse({ success: false, error: 'No sender tab' });
				return true;
			}
			chrome.tabs.remove(tabId)
				.then(() => sendResponse({ success: true }))
				.catch(error => sendResponse({ success: false, error: error instanceof Error ? error.message : String(error) }));
			return true;
		}

		case 'captchaDetected':
			handleCaptchaDetected(sender)
				.then(() => sendResponse({ success: true }))
				.catch(error => sendResponse({ success: false, error: error instanceof Error ? error.message : String(error) }));
			return true;
		case 'bossLoginRequired':
			handleBossLoginRequired(sender)
				.then(() => sendResponse({ success: true }))
				.catch(error => sendResponse({ success: false, error: error instanceof Error ? error.message : String(error) }));
			return true;
		case 'ensureContentScriptLoaded': {
			const tabId = typedRequest.tabId || sender.tab?.id;
			if (!tabId) {
				sendResponse({ success: false, error: 'No tab ID provided' });
				return true;
			}
			ensureContentScriptLoadedInBackground(tabId)
				.then(() => sendResponse({ success: true }))
				.catch(error => sendResponse({ success: false, error: error instanceof Error ? error.message : String(error) }));
			return true;
		}

		case 'ping':
			sendResponse({ success: true });
			return true;

		default:
			return false;
	}
}

async function runBossDetailTaskQueue(): Promise<void> {
	if (isBossDetailQueueRunning) return;
	isBossDetailQueueRunning = true;

	try {
		const pauseState = await readBossDetailQueuePauseState();
		if (pauseState.paused) {
			console.log('[Joblens] BOSS detail queue paused:', pauseState.reason || 'paused');
			return;
		}

		const tasks = await fetchBossDetailTasks();
		if (tasks.length === 0) return;

		const results = await readJsonlResults(BOSS_DETAIL_RESULTS_FILE);
		const doneUrls = new Set(
			results
				.filter((record: any) => record?.status === 'done' && record?.url)
				.map((record: any) => normalizeBossDetailUrl(record.url))
		);
		const doneJobIds = new Set(
			results
				.filter((record: any) => record?.status === 'done' && (record?.job_id || record?.url))
				.map((record: any) => record.job_id || getBossDetailJobId(record.url))
				.filter(Boolean)
		);
		const doneLocks = await readLockMap(BOSS_DETAIL_DONE_LOCKS_KEY);
		const inflightLocks = await readActiveInflightLocks(BOSS_DETAIL_INFLIGHT_LOCKS_KEY, BOSS_DETAIL_INFLIGHT_TTL_MS, Date.now());
		const pendingTasks = tasks.filter(task => {
			const normalizedUrl = normalizeBossDetailUrl(task.url);
			const jobId = task.jobId || getBossDetailJobId(task.url);
			const lockKey = getBossDetailTaskLockKey(task);
			return !doneUrls.has(normalizedUrl)
				&& !(jobId && doneJobIds.has(jobId))
				&& !doneLocks[lockKey]
				&& !inflightLocks[lockKey];
		});

		if (pendingTasks.length === 0) return;

		console.log('[Joblens] BOSS detail queue processing', pendingTasks.length, 'of', tasks.length, 'tasks');
		for (const task of pendingTasks) {
			const lockKey = getBossDetailTaskLockKey(task);
			const claimed = await claimTask(
				lockKey,
				bossDetailRuntimeClaims,
				BOSS_DETAIL_DONE_LOCKS_KEY,
				BOSS_DETAIL_INFLIGHT_LOCKS_KEY,
				BOSS_DETAIL_INFLIGHT_TTL_MS
			);
			if (!claimed) {
				console.log('[Joblens] BOSS detail queue skip claimed task', task.index + 1, '/', tasks.length);
				continue;
			}

			console.log('[Joblens] BOSS detail task', task.index + 1, '/', tasks.length);
			const result = await processSingleBossDetailUrl(task.url);
			await writeBossDetailResult(task, result.success ? 'done' : 'failed', result.reason);
			await completeTask(lockKey, result.success, bossDetailRuntimeClaims, BOSS_DETAIL_DONE_LOCKS_KEY, BOSS_DETAIL_INFLIGHT_LOCKS_KEY);

			if (!result.success && (result.reason === 'captcha detected' || result.reason === 'login required')) {
				await setBossDetailQueuePaused(true, result.reason);
				break;
			}
			await sleep(2000);
		}
	} catch (error) {
		console.error('[Joblens] BOSS detail queue error:', error);
	} finally {
		isBossDetailQueueRunning = false;
	}
}

async function fetchBossDetailTasks(): Promise<DetailTask[]> {
	try {
		const response = await fetch(BOSS_DETAIL_TASK_FILE);
		const text = await response.text();
		return text.trim().split('\n').filter(Boolean).map((line, index) => {
			try {
				const parsed = JSON.parse(line);
				return { index, url: parsed.url, keyword: parsed.keyword, jobId: parsed.job_id || parsed.jobId };
			} catch {
				return { index, url: line.trim(), keyword: '' };
			}
		});
	} catch {
		return [];
	}
}

async function writeBossDetailResult(task: DetailTask, status: string, error?: string): Promise<void> {
	try {
		const record: any = {
			task_index: task.index,
			url: task.url,
			normalized_url: normalizeBossDetailUrl(task.url),
			job_id: task.jobId || getBossDetailJobId(task.url),
			keyword: task.keyword,
			status,
			recorded_at: new Date().toISOString()
		};
		if (error) record.error = error;

		const existing = await readJsonlResults(BOSS_DETAIL_RESULTS_FILE);
		existing.push(record);
		await writeJsonlResults(BOSS_DETAIL_RESULTS_FILE, existing);
	} catch {}
}

async function runBossListTaskQueue(): Promise<void> {
	if (isBossListQueueRunning) return;
	isBossListQueueRunning = true;

	try {
		const tasks = await fetchBossListTasks();
		if (tasks.length === 0) return;

		const results = await readJsonlResults(BOSS_LIST_RESULTS_FILE);
		const doneTaskIds = new Set(
			results
				.filter((record: any) => record?.status === 'done' && record?.task_id)
				.map((record: any) => String(record.task_id))
		);
		const doneUrls = new Set(
			results
				.filter((record: any) => record?.status === 'done' && record?.url)
				.map((record: any) => normalizeBossListUrl(record.url))
		);
		const doneLocks = await readLockMap(BOSS_LIST_DONE_LOCKS_KEY);
		const inflightLocks = await readActiveInflightLocks(BOSS_LIST_INFLIGHT_LOCKS_KEY, BOSS_LIST_INFLIGHT_TTL_MS, Date.now());

		const pendingTasks = tasks.filter(task => {
			const taskIdStr = String(task.taskId);
			const normalizedUrl = normalizeBossListUrl(task.url);
			const lockKey = getBossListTaskLockKey(task);
			return !doneTaskIds.has(taskIdStr)
				&& !doneUrls.has(normalizedUrl)
				&& !doneLocks[lockKey]
				&& !inflightLocks[lockKey];
		});

		if (pendingTasks.length === 0) return;

		console.log('[Joblens] BOSS list queue processing', pendingTasks.length, 'of', tasks.length, 'tasks');
		for (const task of pendingTasks) {
			const lockKey = getBossListTaskLockKey(task);
			const claimed = await claimTask(
				lockKey,
				bossListRuntimeClaims,
				BOSS_LIST_DONE_LOCKS_KEY,
				BOSS_LIST_INFLIGHT_LOCKS_KEY,
				BOSS_LIST_INFLIGHT_TTL_MS
			);
			if (!claimed) {
				console.log('[Joblens] BOSS list queue skip claimed task', task.index + 1, '/', tasks.length);
				continue;
			}

			console.log('[Joblens] BOSS list task', task.index + 1, '/', tasks.length);
			const result = await processSingleBossListUrl(task.url);
			await writeBossListResult(task, result.success ? 'done' : 'failed', result.reason, result.fileName);
			await completeTask(lockKey, result.success, bossListRuntimeClaims, BOSS_LIST_DONE_LOCKS_KEY, BOSS_LIST_INFLIGHT_LOCKS_KEY);
			await sleep(2000);
		}
	} catch (error) {
		console.error('[Joblens] BOSS list queue error:', error);
	} finally {
		isBossListQueueRunning = false;
	}
}

async function fetchBossListTasks(): Promise<ListTask[]> {
	try {
		const response = await fetch(BOSS_LIST_TASK_FILE);
		const text = await response.text();
		return text.trim().split('\n').filter(Boolean).map((line, index) => {
			try {
				const parsed = JSON.parse(line);
				return { index, url: parsed.url, keyword: parsed.keyword, taskId: parsed.task_id || parsed.taskId };
			} catch {
				return { index, url: line.trim(), keyword: '' };
			}
		});
	} catch {
		return [];
	}
}

async function writeBossListResult(task: ListTask, status: string, error?: string, fileName?: string): Promise<void> {
	try {
		const record: any = {
			task_index: task.index,
			task_id: task.taskId,
			url: task.url,
			normalized_url: normalizeBossListUrl(task.url),
			keyword: task.keyword,
			status,
			recorded_at: new Date().toISOString()
		};
		if (fileName) record.file_name = fileName;
		if (error) record.error = error;

		const existing = await readJsonlResults(BOSS_LIST_RESULTS_FILE);
		existing.push(record);
		await writeJsonlResults(BOSS_LIST_RESULTS_FILE, existing);
	} catch {}
}

async function startBossDetailQueuePolling(): Promise<void> {
	const pauseState = await readBossDetailQueuePauseState();
	if (pauseState.paused) {
		console.log('[Joblens] BOSS detail queue polling not started: paused:', pauseState.reason || 'paused');
		try { await chrome.action.setBadgeBackgroundColor({ color: '#b91c1c' }); } catch {}
		try { await chrome.action.setBadgeText({ text: 'CAP' }); } catch {}
		return;
	}

	console.log('[Joblens] BOSS detail queue polling started (alarms, 5s)');
	chrome.alarms.create('bossDetailQueuePoll', { periodInMinutes: 5 / 60 });
	runBossDetailTaskQueue();
}

function startBossListQueuePolling(): void {
	console.log('[Joblens] BOSS list queue polling started (alarms, 5s)');
	chrome.alarms.create('bossListQueuePoll', { periodInMinutes: 5 / 60 });
	runBossListTaskQueue();
}
async function startDetailQueuePolling(): Promise<void> {
	const pauseState = await readDetailQueuePauseState();
	if (pauseState.paused) {
		console.log('[Joblens] Detail queue polling not started: paused:', pauseState.reason || 'paused');
		try { await chrome.action.setBadgeBackgroundColor({ color: '#b91c1c' }); } catch {}
		try { await chrome.action.setBadgeText({ text: 'CAP' }); } catch {}
		return;
	}

	console.log('[Joblens] Detail queue polling started (alarms, 5s)');
	chrome.alarms.create('detailQueuePoll', { periodInMinutes: 5 / 60 });
	runDetailTaskQueue();
}

function startListQueuePolling(): void {
	console.log('[Joblens] List queue polling started (alarms, 5s)');
	chrome.alarms.create('listQueuePoll', { periodInMinutes: 5 / 60 });
	runListTaskQueue();
}

async function initialize(): Promise<void> {
	chrome.alarms.onAlarm.addListener((alarm) => {
		if (alarm.name === 'detailQueuePoll') {
			runDetailTaskQueue();
		}
		if (alarm.name === 'listQueuePoll') {
			runListTaskQueue();
		}
		if (alarm.name === 'bossDetailQueuePoll') {
			runBossDetailTaskQueue();
		}
		if (alarm.name === 'bossListQueuePoll') {
			runBossListTaskQueue();
		}
	});

	chrome.runtime.onMessage.addListener(handleRuntimeMessage);
	await startDetailQueuePolling();
	startListQueuePolling();
	await startBossDetailQueuePolling();
	startBossListQueuePolling();
	console.log('[Joblens] Background script initialized');
}

initialize().catch(error => {
	console.error('[Joblens] Failed to initialize background script:', error);
});
