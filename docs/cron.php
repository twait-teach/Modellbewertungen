<?php
/*
 * Startknopf fuer den halbstuendlichen Datenlauf.
 *
 * All-Inkl kann Cronjobs nur ueber eine URL ausfuehren, nicht direkt ueber die
 * Kommandozeile. Deshalb liegt diese winzige Datei im oeffentlichen Verzeichnis
 * und startet das eigentliche Laufskript (skripte/lauf.sh), das eine Ebene
 * darueber liegt und selbst nicht aus dem Netz erreichbar ist.
 *
 * Schutz: Der Aufruf braucht ein Geheimwort, das in
 *     <Konto>/wetter/cron-schluessel.txt
 * steht -- also AUSSERHALB des Webverzeichnisses und ausserhalb des
 * Repositories. Ohne dieses Wort passiert nichts. Sonst koennte jeder die
 * Datenabrufe ausloesen und die Abruflimits von open-meteo aufbrauchen.
 *
 * Der Lauf wird im Hintergrund gestartet und die Antwort sofort geschickt.
 * Sonst wuerde der Webserver den Aufruf nach seiner Zeitgrenze abschneiden und
 * den Lauf mittendrin abbrechen.
 */

header('Content-Type: text/plain; charset=utf-8');

$wurzel       = dirname(__DIR__);          // .../wetter/programm
$schluesselDatei = dirname($wurzel) . '/cron-schluessel.txt';   // .../wetter/
$protokoll    = dirname($wurzel) . '/lauf.log';

if (!is_readable($schluesselDatei)) {
    http_response_code(500);
    echo "Kein Schluessel hinterlegt.\n";
    exit;
}

$erwartet = trim((string) file_get_contents($schluesselDatei));
$gegeben  = isset($_GET['schluessel']) ? (string) $_GET['schluessel'] : '';

// hash_equals vergleicht in gleichbleibender Zeit -- verhindert, dass sich das
// Geheimwort durch Messen der Antwortzeit Zeichen fuer Zeichen erraten laesst.
if ($erwartet === '' || !hash_equals($erwartet, $gegeben)) {
    http_response_code(403);
    echo "Nicht erlaubt.\n";
    exit;
}

if (!function_exists('shell_exec')) {
    http_response_code(500);
    echo "shell_exec ist auf diesem Server abgeschaltet.\n";
    exit;
}

// Zwei Laeufe, ein Startknopf: ohne Angabe der vollstaendige Wetterlauf,
// mit "&teil=station" nur die Wetterstation (die darf viel haeufiger laufen).
$teil   = isset($_GET['teil']) ? (string) $_GET['teil'] : '';
$skript = ($teil === 'station') ? 'skripte/lauf_station.sh' : 'skripte/lauf.sh';

$befehl = 'cd ' . escapeshellarg($wurzel)
        . ' && nohup sh ' . escapeshellarg($skript) . ' >> ' . escapeshellarg($protokoll) . ' 2>&1 &';
shell_exec($befehl);

echo "Lauf gestartet (" . ($teil === 'station' ? 'Station' : 'Wetter') . ") "
   . gmdate('Y-m-d H:i') . "Z\n";
