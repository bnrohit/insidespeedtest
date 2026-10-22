<?php

require 'includes/html/graphs/common.inc.php';
$rrd_filename = Rrd::name($device['hostname'], ['app', 'gmcs_vyos_speedtest', $app->app_id]);
$colours = 'mixed';
$nototal = (($width < 224) ? 1 : 0);
$unit_text = 'ms';
$rrd_list = [
    ['filename' => $rrd_filename, 'descr' => 'inside_ping', 'ds' => 'inside_ping', 'colour' => '3366CC'],
    ['filename' => $rrd_filename, 'descr' => 'inside_jitter', 'ds' => 'inside_jitter', 'colour' => '00A896'],
];
require 'includes/html/graphs/generic_multi_line.inc.php';
