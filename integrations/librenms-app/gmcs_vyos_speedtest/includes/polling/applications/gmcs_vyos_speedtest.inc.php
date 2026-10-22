<?php

// GMCS: VyOS measures locally; this poller only reads the router's cached SNMP extend.
// Separate app name avoids overwriting pre-existing local vyos_speedtest or RRDs.
use Illuminate\Support\Facades\Log;
use LibreNMS\Exceptions\JsonAppException;
use LibreNMS\RRD\RrdDefinition;

$name = 'gmcs_vyos_speedtest';
try {
    $report = json_app_get($device, $name, 1)['data'];
} catch (JsonAppException $e) {
    Log::info($name . ': ' . $e->getCode() . ': ' . $e->getMessage());
    update_application($app, $e->getCode() . ': ' . $e->getMessage(), []);
    return;
}

$rrd_def = RrdDefinition::make();
$mapping = [
    'ookla' => [
        'download_mbps' => 'ookla_down',
        'upload_mbps' => 'ookla_up',
        'latency_ms' => 'ookla_ping',
        'jitter_ms' => 'ookla_jitter',
        'loss_pct' => 'ookla_loss',
    ],
    'inside' => [
        'download_mbps' => 'inside_down',
        'upload_mbps' => 'inside_up',
        'latency_ms' => 'inside_ping',
        'jitter_ms' => 'inside_jitter',
        'loss_pct' => 'inside_loss',
    ],
];
$fields = [];
foreach ($mapping as $source => $values) {
    $sample = $report[$source] ?? [];
    $ok = ($sample['status'] ?? '') === 'ok';
    foreach ($values as $incoming => $ds) {
        $value = $sample[$incoming] ?? null;
        $maximum = ($incoming === 'loss_pct' ? 100 : 100000);
        $fields[$ds] = ($ok && is_numeric($value) && is_finite((float)$value)
            && $value >= 0 && $value <= $maximum) ? (float)$value : null;
        $rrd_def->addDataset($ds, 'GAUGE', 0, $maximum);
    }
}

$tags = [
    'name' => $name,
    'app_id' => $app->app_id,
    'rrd_name' => ['app', $name, $app->app_id],
    'rrd_def' => $rrd_def,
];
app('Datastore')->put($device, 'app', $tags, $fields);
update_application($app, 'OK (cached router measurements)', $fields);
