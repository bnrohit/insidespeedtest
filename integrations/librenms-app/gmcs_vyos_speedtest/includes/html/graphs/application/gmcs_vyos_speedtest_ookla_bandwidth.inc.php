<?php

require 'includes/html/graphs/common.inc.php';
$rrd_filename = Rrd::name($device['hostname'], ['app', 'gmcs_vyos_speedtest', $app->app_id]);
$colours = 'mixed';
$nototal = (($width < 224) ? 1 : 0);
$unit_text = 'Mbps';
$rrd_list = [
    ['filename' => $rrd_filename, 'descr' => 'ookla_down', 'ds' => 'ookla_down', 'colour' => '3366CC'],
    ['filename' => $rrd_filename, 'descr' => 'ookla_up', 'ds' => 'ookla_up', 'colour' => '00A896'],
];
require 'includes/html/graphs/generic_multi_line.inc.php';
