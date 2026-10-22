<?php
// GMCS VyOS *local* speed test. Reads cached SNMP extend, never initiates tests.
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
$def=RrdDefinition::make();
$mapping=[
    'download_mbps'=>'inside_down',
    'upload_mbps'=>'inside_up',
    'latency_ms'=>'inside_ping',
    'jitter_ms'=>'inside_jitter',
    'loss_pct'=>'inside_loss',
];
$fields=[];
$ok=($report['status'] ?? '') === 'ok';
foreach ($mapping as $field => $ds) {
    $value=$report[$field] ?? null;
    $max=($field==='loss_pct') ? 100 : 100000;
    $fields[$ds]=($ok && is_numeric($value) && is_finite((float) $value)
       && (float) $value>=0 && (float) $value<=$max) ? (float) $value : null;
    $def->addDataset($ds,'GAUGE',0,$max);
}
$tags=['name'=>$name,'app_id'=>$app->app_id,
       'rrd_name'=>['app',$name,$app->app_id],'rrd_def'=>$def];
app('Datastore')->put($device,'app',$tags,$fields);
update_application($app,$ok ? 'OK (VyOS local HTTP test)' : 'No fresh VyOS result', $fields);
