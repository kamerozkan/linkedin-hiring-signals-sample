import { readFile, readdir, stat } from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');

const inputFiles = [
    '01_github_changes_only.json',
    '02_github_current_snapshot.json',
    '03_github_verified_apply_links.json',
];

const outputFiles = [
    '01_live_new_official_apply.json',
    '02_replay_changed_location.json',
    '03_replay_closed_confirmed.json',
];

const allowedInputKeys = new Set([
    'companies',
    'maxJobsPerCompany',
    'closureConfirmationScans',
    'emitInitialSnapshot',
    'emitCurrentSnapshot',
    'stateStoreName',
    'stateNamespace',
    'closedJobRetentionDays',
    'maxConcurrency',
    'strictClosureQualityGate',
    'verifyApplyLinks',
    'strictVerificationQualityGate',
    'verifierActorId',
    'maxJobsToVerify',
    'verificationMaxTotalChargeUsd',
    'webhookUrl',
    'webhookSecret',
    'webhookBatchSize',
    'proxyConfiguration',
]);

const fail = (message) => {
    throw new Error(message);
};

const assert = (condition, message) => {
    if (!condition) fail(message);
};

const readJson = async (relativePath) => {
    const text = await readFile(path.join(root, relativePath), 'utf8');
    try {
        return JSON.parse(text);
    } catch (error) {
        fail(`${relativePath}: invalid JSON: ${error.message}`);
    }
};

const walk = async (directory) => {
    const entries = await readdir(directory, { withFileTypes: true });
    const files = [];

    for (const entry of entries) {
        if (entry.name === '.git' || entry.name === 'node_modules') continue;
        const absolutePath = path.join(directory, entry.name);
        if (entry.isDirectory()) files.push(...await walk(absolutePath));
        else files.push(absolutePath);
    }

    return files;
};

const validateInput = (file, input) => {
    assert(input && typeof input === 'object' && !Array.isArray(input), `${file}: input must be an object`);
    assert(Object.keys(input).every((key) => allowedInputKeys.has(key)), `${file}: unknown input property`);
    assert(Array.isArray(input.companies) && input.companies.length > 0, `${file}: companies must be non-empty`);
    assert(input.companies.every((company) => /^https:\/\/www\.linkedin\.com\/company\/[a-z0-9-]+\/$/.test(company)), `${file}: use canonical LinkedIn company URLs`);
    assert(input.stateNamespace === 'auto', `${file}: stateNamespace must be auto for saved Tasks`);
    assert(input.closureConfirmationScans === 2, `${file}: closureConfirmationScans must demonstrate the safe default`);
    assert(input.emitInitialSnapshot === true, `${file}: first-seen jobs must be emitted`);
    assert(input.strictClosureQualityGate === false, `${file}: strict closure gate must be opt-in`);
    assert(typeof input.emitCurrentSnapshot === 'boolean', `${file}: emitCurrentSnapshot must be explicit`);
    assert(typeof input.verifyApplyLinks === 'boolean', `${file}: verifyApplyLinks must be explicit`);
};

const valueMatchesType = (value, type) => {
    if (type === 'null') return value === null;
    if (type === 'array') return Array.isArray(value);
    if (type === 'object') return value !== null && typeof value === 'object' && !Array.isArray(value);
    if (type === 'number') return typeof value === 'number' && Number.isFinite(value);
    if (type === 'integer') return Number.isInteger(value);
    return typeof value === type;
};

const isCalendarDate = (value) => {
    if (typeof value !== 'string') return false;
    const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(value);
    if (!match) return false;
    const year = Number(match[1]);
    const month = Number(match[2]);
    const day = Number(match[3]);
    const parsed = new Date(Date.UTC(year, month - 1, day));
    return parsed.getUTCFullYear() === year
        && parsed.getUTCMonth() === month - 1
        && parsed.getUTCDate() === day;
};

const validateFormat = (value, format, location) => {
    if (value === null || !format) return;

    if (format === 'uri') {
        let parsed;
        try {
            parsed = new URL(value);
        } catch {
            fail(`${location}: invalid URI`);
        }
        assert(['http:', 'https:'].includes(parsed.protocol), `${location}: URI must use HTTP or HTTPS`);
    }

    if (format === 'date') {
        assert(isCalendarDate(value), `${location}: invalid date`);
    }

    if (format === 'date-time') {
        assert(typeof value === 'string'
            && isCalendarDate(value.slice(0, 10))
            && /^\d{4}-\d{2}-\d{2}T/.test(value)
            && !Number.isNaN(Date.parse(value)), `${location}: invalid date-time`);
    }
};

const validateOutput = (file, record, schema) => {
    assert(record && typeof record === 'object' && !Array.isArray(record), `${file}: record must be an object`);
    const propertyNames = new Set(Object.keys(schema.properties));

    for (const key of schema.required) assert(Object.hasOwn(record, key), `${file}: missing required property ${key}`);
    assert(Object.keys(record).every((key) => propertyNames.has(key)), `${file}: additional property is not allowed`);

    for (const [key, definition] of Object.entries(schema.properties)) {
        if (!Object.hasOwn(record, key)) continue;
        const value = record[key];
        const types = Array.isArray(definition.type) ? definition.type : [definition.type];
        assert(types.some((type) => valueMatchesType(value, type)), `${file}.${key}: unexpected type`);

        if (definition.enum) assert(definition.enum.includes(value), `${file}.${key}: value is not in enum`);
        if (definition.const !== undefined) assert(value === definition.const, `${file}.${key}: value does not match const`);
        if (typeof value === 'number' && definition.minimum !== undefined) assert(value >= definition.minimum, `${file}.${key}: below minimum`);
        if (typeof value === 'number' && definition.maximum !== undefined) assert(value <= definition.maximum, `${file}.${key}: above maximum`);
        if (Array.isArray(value) && definition.items?.type) {
            assert(value.every((item) => valueMatchesType(item, definition.items.type)), `${file}.${key}: invalid array item type`);
        }
        validateFormat(value, definition.format, `${file}.${key}`);
    }
};

const validateMarkdownLinks = async (files) => {
    const markdownFiles = files.filter((file) => file.endsWith('.md'));
    const linkPattern = /\[[^\]]*\]\(([^)]+)\)/g;

    for (const markdownFile of markdownFiles) {
        const text = await readFile(markdownFile, 'utf8');
        for (const match of text.matchAll(linkPattern)) {
            const target = match[1].split('#', 1)[0];
            if (!target || /^(?:https?:|mailto:)/.test(target)) continue;
            const localPath = path.resolve(path.dirname(markdownFile), decodeURIComponent(target));
            try {
                await stat(localPath);
            } catch {
                fail(`${path.relative(root, markdownFile)}: missing local link target ${target}`);
            }
        }
    }
};

const files = await walk(root);

assert(isCalendarDate('2024-02-29'), 'validator must accept a real leap day');
assert(!isCalendarDate('2026-02-30'), 'validator must reject an impossible calendar date');

for (const file of files.filter((candidate) => candidate.endsWith('.json'))) {
    await readJson(path.relative(root, file));
}

const inputs = await Promise.all(inputFiles.map(async (file) => [file, await readJson(file)]));
for (const [file, input] of inputs) validateInput(file, input);

assert(inputs[0][1].emitCurrentSnapshot === false && inputs[0][1].verifyApplyLinks === false, '01 must be a changes-only quick start');
assert(inputs[1][1].emitCurrentSnapshot === true && inputs[1][1].verifyApplyLinks === false, '02 must be a full snapshot example');
assert(inputs[2][1].emitCurrentSnapshot === false && inputs[2][1].verifyApplyLinks === true, '03 must be a separate verification example');
assert(inputs[2][1].strictVerificationQualityGate === true, '03 must demonstrate the strict verification gate');
assert(Number.isInteger(inputs[2][1].maxJobsToVerify) && inputs[2][1].maxJobsToVerify >= 1 && inputs[2][1].maxJobsToVerify <= 500, '03 has an invalid verification job limit');
assert(typeof inputs[2][1].verificationMaxTotalChargeUsd === 'number' && inputs[2][1].verificationMaxTotalChargeUsd >= 0.004, '03 has an invalid verification charge limit');

const schema = await readJson('dataset_record.schema.json');
const outputs = await Promise.all(outputFiles.map(async (file) => [file, await readJson(file)]));
for (const [file, output] of outputs) validateOutput(file, output, schema);

await validateMarkdownLinks(files);

for (const file of files) {
    const text = await readFile(file, 'utf8');
    assert(!text.includes('\u2014'), `${path.relative(root, file)}: Unicode U+2014 is not allowed`);
}

console.log(`Validated ${inputFiles.length} inputs, ${outputFiles.length} outputs, JSON syntax, local links, and typography.`);
