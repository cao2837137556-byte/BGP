#!/usr/bin/env node
"use strict";

const fs = require("fs");
const path = require("path");
const readline = require("readline");

function parseArgs(argv) {
    const args = {};
    for (let index = 2; index < argv.length; index += 2) {
        const key = argv[index];
        const value = argv[index + 1];
        if (!key || !key.startsWith("--") || value === undefined) {
            throw new Error(`Invalid argument sequence near ${key || "<end>"}`);
        }
        args[key.slice(2)] = value;
    }
    return args;
}

function requireFromRoot(root, relativePath) {
    return require(path.join(root, relativePath)).default;
}

async function readJsonLines(filePath) {
    const rows = [];
    const stream = fs.createReadStream(filePath, {encoding: "utf8"});
    const reader = readline.createInterface({
        input: stream,
        crlfDelay: Infinity
    });
    for await (const line of reader) {
        if (line.trim()) {
            rows.push(JSON.parse(line));
        }
    }
    return rows;
}

async function main() {
    const args = parseArgs(process.argv);
    const bgpalerterRoot = path.resolve(
        process.env.BGPALERTER_ROOT || args["bgpalerter-root"] || ""
    );
    const inputPath = path.resolve(args.input || "");
    const outputPath = path.resolve(args.output || "");
    const metricsPath = path.resolve(args.metrics || "");

    if (!fs.existsSync(path.join(bgpalerterRoot, "src", "consumer.js"))) {
        throw new Error(`BGPalerter source root is invalid: ${bgpalerterRoot}`);
    }
    if (!fs.existsSync(inputPath)) {
        throw new Error(`Input JSONL does not exist: ${inputPath}`);
    }

    const Consumer = requireFromRoot(bgpalerterRoot, "src/consumer.js");
    const Monitor = requireFromRoot(bgpalerterRoot, "src/monitors/monitor.js");
    const PubSub = requireFromRoot(bgpalerterRoot, "src/utils/pubSub.js");
    const componentPackage = require(path.join(bgpalerterRoot, "package.json"));

    class CanonicalContractConnector {
        static transform(envelope) {
            if (!envelope || envelope.type !== "canonical_observation_v2") {
                return [];
            }
            const canonical = JSON.parse(JSON.stringify(envelope.data));
            return [{
                type: canonical.type === "W" ? "withdrawal" : "announcement",
                prefix: canonical.prefix,
                peer: canonical.peer_address,
                peerAS: canonical.peer_asn,
                timestamp: Number(canonical.ts) * 1000,
                communities: canonical.communities || [],
                nextHop: canonical.next_hop,
                observationId: canonical.observation_id,
                canonical
            }];
        }
    }

    class ContractLedgerMonitor extends Monitor {
        updateMonitoredResources = () => {};

        filter = () => true;

        squashAlerts = () => "canonical contract passthrough";

        monitor = (message) =>
            new Promise((resolve) => {
                this.publishAlert(
                    message.observationId,
                    message.prefix || "no-prefix",
                    {
                        prefix: message.prefix || "0.0.0.0/0",
                        description: "N-FRONTEND-FIT-0A contract probe"
                    },
                    message,
                    {
                        runtimeDecision: "contract_passthrough",
                        truthLabelProduced: false
                    }
                );
                resolve(true);
            });
    }

    class ContractLedgerReport {
        constructor(channels, params, env) {
            this.rows = [];
            for (const channel of channels) {
                env.pubSub.subscribe(channel, (content) => {
                    const alert = content.data[0];
                    this.rows.push({
                        ...alert.matchedMessage.canonical,
                        runtime_decision: alert.extra.runtimeDecision,
                        runtime_sequence: this.rows.length,
                        runtime_origin: content.origin
                    });
                });
            }
        }
    }

    const loggedErrors = [];
    const pubSub = new PubSub();
    const env = {
        version: componentPackage.version,
        clientId: "n-frontend-fit-0a",
        config: {
            alertOnlyOnce: false,
            notificationIntervalSeconds: 14400,
            checkFadeOffGroupsSeconds: 3600,
            fadeOffSeconds: 3600,
            persistStatus: false,
            connectors: [{
                name: "can",
                class: CanonicalContractConnector
            }],
            monitors: [{
                name: "canonical-contract-monitor",
                channel: "contract-ledger",
                params: {
                    maxDataSamples: 1
                },
                class: ContractLedgerMonitor
            }],
            reports: [{
                channels: ["contract-ledger"],
                params: {},
                class: ContractLedgerReport
            }]
        },
        logger: {
            log: (entry) => {
                if (entry && entry.level === "error") {
                    loggedErrors.push(String(entry.message));
                }
            }
        },
        pubSub,
        rpki: null,
        storage: null
    };
    const inputStub = {
        onChange: () => {}
    };

    const inputRows = await readJsonLines(inputPath);
    const consumer = new Consumer(env, inputStub);
    const start = process.hrtime.bigint();
    for (const row of inputRows) {
        consumer.dispatch([{
            connector: "can",
            message: {
                type: "canonical_observation_v2",
                data: row
            }
        }]);
    }
    await new Promise((resolve) => setImmediate(resolve));
    const elapsedSeconds = Number(process.hrtime.bigint() - start) / 1e9;
    const outputRows = consumer.reports[0].rows;

    fs.mkdirSync(path.dirname(outputPath), {recursive: true});
    fs.writeFileSync(
        outputPath,
        outputRows.map((row) => JSON.stringify(row)).join("\n") + "\n",
        "utf8"
    );
    const metrics = {
        component: "BGPalerter",
        component_version: componentPackage.version,
        input_rows: inputRows.length,
        output_rows: outputRows.length,
        elapsed_seconds: elapsedSeconds,
        rows_per_second: elapsedSeconds > 0 ? inputRows.length / elapsedSeconds : null,
        peak_rss_bytes: process.memoryUsage().rss,
        logged_error_count: loggedErrors.length,
        logged_errors: loggedErrors,
        network_connector_used: false,
        native_boundaries_reused: [
            "Consumer.dispatch",
            "Monitor.filter",
            "Monitor.monitor",
            "Monitor.publishAlert",
            "PubSub.publish"
        ]
    };
    fs.writeFileSync(metricsPath, JSON.stringify(metrics, null, 2) + "\n", "utf8");

    if (loggedErrors.length || outputRows.length !== inputRows.length) {
        process.exitCode = 2;
    }
}

main()
    .then(() => {
        if (!process.exitCode) {
            process.exit(0);
        }
    })
    .catch((error) => {
        console.error(error.stack || error.message);
        process.exit(1);
    });
