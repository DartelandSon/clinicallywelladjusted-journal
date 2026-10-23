<?php
declare(strict_types=1);
/**
 * CLI-only, secret-free static deployer. Install OUTSIDE every public web root.
 * Fetch one immutable Git commit, validate every file, then switch one symlink.
 * This never executes code downloaded from the publication repository.
 */
if (PHP_SAPI !== 'cli') {
    http_response_code(404);
    exit;
}

function fetchUrl(string $url, int $limit): string {
    if (!function_exists('curl_init')) throw new RuntimeException('PHP cURL is required');
    $handle = curl_init($url);
    $body = '';
    curl_setopt_array($handle, [
        CURLOPT_FOLLOWLOCATION => false,
        CURLOPT_CONNECTTIMEOUT => 15,
        CURLOPT_TIMEOUT => 90,
        CURLOPT_SSL_VERIFYPEER => true,
        CURLOPT_SSL_VERIFYHOST => 2,
        CURLOPT_PROTOCOLS => CURLPROTO_HTTPS,
        CURLOPT_HTTPHEADER => ['User-Agent: CWA-Static-Publisher/1.0', 'Accept: application/vnd.github+json'],
        CURLOPT_WRITEFUNCTION => function ($ch, string $chunk) use (&$body, $limit): int {
            if (strlen($body) + strlen($chunk) > $limit) return 0;
            $body .= $chunk;
            return strlen($chunk);
        },
    ]);
    $ok = curl_exec($handle);
    $code = curl_getinfo($handle, CURLINFO_HTTP_CODE);
    $error = curl_error($handle);
    curl_close($handle);
    if ($ok === false || $code !== 200) {
        throw new RuntimeException("Download failed (HTTP $code): $error");
    }
    return $body;
}

function validManifest(array $manifest): array {
    if (($manifest['schema'] ?? null) !== 1 ||
        ($manifest['site'] ?? '') !== 'https://clinicallywelladjusted.com' ||
        !preg_match('/^[a-f0-9]{64}$/D', $manifest['release'] ?? '') ||
        !is_array($manifest['files'] ?? null) ||
        count($manifest['files']) > 2000) {
        throw new RuntimeException('Invalid publication manifest');
    }
    $seen = [];
    $total = 0;
    foreach ($manifest['files'] as $file) {
        $path = $file['path'] ?? '';
        if (!is_string($path) ||
            !preg_match('~^[a-zA-Z0-9][a-zA-Z0-9_/-]*\.(html|css|js|json|xml|txt|svg|png|jpg|jpeg|webp|woff2)$~D', $path) ||
            str_contains($path, '//') || isset($seen[$path]) ||
            !is_int($file['bytes'] ?? null) || $file['bytes'] < 0 || $file['bytes'] > 10 * 1024 * 1024 ||
            !preg_match('/^[a-f0-9]{64}$/D', $file['sha256'] ?? '')) {
            throw new RuntimeException('Unsafe or duplicate publication path');
        }
        $seen[$path] = true;
        $total += $file['bytes'];
    }
    if ($total > 50 * 1024 * 1024) throw new RuntimeException('Publication exceeds size limit');
    foreach (['index.html', '404.html', 'authorship/index.html', 'sitemap.xml', 'robots.txt',
              'google7807d41d479e3865.html'] as $required) {
        if (!isset($seen[$required])) throw new RuntimeException("Missing required public file: $required");
    }
    return $manifest['files'];
}

function hostingRules(): string {
    return <<<'HTACCESS'
Options -Indexes -ExecCGI
DirectoryIndex index.html
ErrorDocument 404 /404.html
<IfModule mod_rewrite.c>
RewriteEngine On
# Leave certificate challenges to the host.
RewriteCond %{REQUEST_URI} !^/\.well-known/(acme-challenge|pki-validation)/ [NC]
RewriteCond %{HTTPS} !=on [OR]
RewriteCond %{HTTP_HOST} !^clinicallywelladjusted\.com$ [NC]
RewriteRule ^ https://clinicallywelladjusted.com%{REQUEST_URI} [R=301,L,NE]
RewriteRule ^wp-sitemap(?:-[a-z0-9-]+)?\.xml$ /sitemap.xml [R=301,L]
RewriteRule ^sitemap_index\.xml$ /sitemap.xml [R=301,L]
RewriteRule ^feed/?$ /feed.xml [R=301,L]
</IfModule>
<FilesMatch "\.(php[0-9]?|phtml|phar|cgi|pl|py|sh|env|ini|log|sql)$">
Require all denied
</FilesMatch>
<IfModule mod_headers.c>
Header always set X-Content-Type-Options "nosniff"
Header always set Referrer-Policy "strict-origin-when-cross-origin"
Header always set Content-Security-Policy "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; font-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'none'"
</IfModule>
HTACCESS;
}

function deploy(array $config): void {
    $repo = $config['repository'] ?? '';
    $branch = $config['branch'] ?? 'main';
    $base = rtrim($config['directory'] ?? '', '/');
    if (!preg_match('~^[a-zA-Z0-9_-]+/[a-zA-Z0-9_.-]+$~D', $repo) ||
        !preg_match('~^[a-zA-Z0-9_-]+$~D', $branch) ||
        !str_starts_with($base, '/') || str_contains($base, '..') || !is_dir($base)) {
        throw new RuntimeException('Invalid private deploy configuration');
    }
    $lock = fopen($base . '/deploy.lock', 'c');
    if (!$lock || !flock($lock, LOCK_EX | LOCK_NB)) return;
    $commit = json_decode(fetchUrl("https://api.github.com/repos/$repo/commits/$branch", 1024 * 1024), true, 512, JSON_THROW_ON_ERROR);
    $sha = $commit['sha'] ?? '';
    if (!preg_match('/^[a-f0-9]{40}$/D', $sha)) throw new RuntimeException('Invalid commit identifier');
    $statePath = $base . '/last-success.json';
    $state = is_file($statePath) ? json_decode(file_get_contents($statePath), true) : [];
    if (($state['commit'] ?? '') === $sha && is_link($base . '/current') && is_file($base . '/current/index.html')) return;
    $rawRoot = "https://raw.githubusercontent.com/$repo/$sha/dist/";
    $manifest = json_decode(fetchUrl($rawRoot . 'manifest.json', 1024 * 1024), true, 512, JSON_THROW_ON_ERROR);
    $files = validManifest($manifest);
    $release = $base . '/releases/' . $sha;
    if (!is_dir($release) && !mkdir($release, 0755, true)) throw new RuntimeException('Cannot create release directory');
    foreach ($files as $file) {
        $target = $release . '/' . $file['path'];
        if (is_file($target) && filesize($target) === $file['bytes'] && hash_file('sha256', $target) === $file['sha256']) continue;
        $bytes = fetchUrl($rawRoot . $file['path'], $file['bytes'] + 1);
        if (strlen($bytes) !== $file['bytes'] || !hash_equals($file['sha256'], hash('sha256', $bytes))) {
            throw new RuntimeException('Downloaded file failed integrity check');
        }
        if (!is_dir(dirname($target)) && !mkdir(dirname($target), 0755, true)) throw new RuntimeException('Cannot create public directory');
        if (file_put_contents($target . '.incoming', $bytes, LOCK_EX) !== strlen($bytes)) throw new RuntimeException('Incomplete public file write');
        chmod($target . '.incoming', 0644);
        if (!rename($target . '.incoming', $target)) throw new RuntimeException('Cannot finalize public file');
    }
    $disclosure = html_entity_decode(strip_tags(file_get_contents($release . '/authorship/index.html')), ENT_QUOTES | ENT_HTML5);
    if (!str_contains($disclosure, "single man's life") || !str_contains($disclosure, "may not perfectly reflect")) {
        throw new RuntimeException('Required authorship disclosure is incomplete');
    }
    file_put_contents($release . '/.htaccess', hostingRules() . "\n");
    file_put_contents($release . '/deployment.json', json_encode([
        'commit' => $sha, 'release' => $manifest['release'], 'deployed_at' => gmdate('c')
    ], JSON_PRETTY_PRINT | JSON_UNESCAPED_SLASHES) . "\n");
    $current = $base . '/current';
    if (file_exists($current) && !is_link($current)) throw new RuntimeException('Refusing to replace an unmanaged directory');
    $next = $base . '/current-next-' . bin2hex(random_bytes(6));
    if (!symlink('releases/' . $sha, $next) || !rename($next, $current)) {
        throw new RuntimeException('Cannot activate the complete release');
    }
    file_put_contents($statePath . '.new', json_encode([
        'commit' => $sha, 'release' => $manifest['release'], 'deployed_at' => gmdate('c')
    ], JSON_PRETTY_PRINT) . "\n", LOCK_EX);
    chmod($statePath . '.new', 0600);
    rename($statePath . '.new', $statePath);
    echo gmdate('c') . " Published $sha\n";
}

if (realpath($_SERVER['SCRIPT_FILENAME'] ?? '') === __FILE__) {
    try {
        $configFile = $argv[1] ?? __DIR__ . '/config.json';
        $config = json_decode(file_get_contents($configFile), true, 512, JSON_THROW_ON_ERROR);
        deploy($config);
    } catch (Throwable $error) {
        fwrite(STDERR, gmdate('c') . ' ' . $error->getMessage() . "\n");
        exit(1);
    }
}
