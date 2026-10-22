<?php

$graphs = [
    'gmcs_vyos_speedtest_ookla_bandwidth' => 'Ookla - Bandwidth',
    'gmcs_vyos_speedtest_ookla_ping' => 'Ookla - Ping / Jitter',
    'gmcs_vyos_speedtest_local_bandwidth' => 'Local - inside - Bandwidth',
    'gmcs_vyos_speedtest_local_ping' => 'Local - inside - Ping / Jitter',
];
foreach ($graphs as $key => $label) {
    $graph_type = $key;
    $graph_array['height'] = '100';
    $graph_array['width'] = '215';
    $graph_array['to'] = \App\Facades\LibrenmsConfig::get('time.now');
    $graph_array['id'] = $app['app_id'];
    $graph_array['type'] = 'application_' . $key;
    echo '<div class="panel panel-default"><div class="panel-heading">';
    echo '<h3 class="panel-title">' . htmlspecialchars($label) . '</h3></div>';
    echo '<div class="panel-body"><div class="row">';
    include 'includes/html/print-graphrow.inc.php';
    echo '</div></div></div>';
}
