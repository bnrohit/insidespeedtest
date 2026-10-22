<?php
// Native LibreNMS Apps tab; the existing Ookla application remains untouched.
$graphs=[
 'gmcs_vyos_speedtest_local_bandwidth'=>'GMCS Inside - Download / Upload',
 'gmcs_vyos_speedtest_local_ping'=>'GMCS Inside - Latency / Jitter',
 'gmcs_vyos_speedtest_local_loss'=>'GMCS Inside - Packet Loss',
];
foreach ($graphs as $key=>$label) {
    $graph_array['height']='100';
    $graph_array['width']='215';
    $graph_array['to']=\App\Facades\LibrenmsConfig::get('time.now');
    $graph_array['id']=$app['app_id'];
    $graph_array['type']='application_'.$key;
    echo '<div class="panel panel-default"><div class="panel-heading">';
    echo '<h3 class="panel-title">'.htmlspecialchars($label).'</h3></div>';
    echo '<div class="panel-body"><div class="row">';
    include 'includes/html/print-graphrow.inc.php';
    echo '</div></div></div>';
}
