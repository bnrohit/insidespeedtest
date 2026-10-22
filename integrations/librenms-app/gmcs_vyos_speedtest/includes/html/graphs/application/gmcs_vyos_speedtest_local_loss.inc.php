<?php
require 'includes/html/graphs/common.inc.php';
$rrd_filename=Rrd::name($device['hostname'],['app','gmcs_vyos_speedtest',$app->app_id]);
$colours='mixed';
$nototal=(($width<224) ? 1 : 0);
$unit_text='%';
$rrd_list=[['filename'=>$rrd_filename,'descr'=>'Loss %','ds'=>'inside_loss','colour'=>'DC7633']];
require 'includes/html/graphs/generic_multi_line.inc.php';
