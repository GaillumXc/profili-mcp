param(
    [Parameter(Mandatory = $true)][string]$Dbq,
    [Parameter(Mandatory = $false)][string]$Sql,
    [Parameter(Mandatory = $false)][string]$SqlFile,
    [ValidateSet('query', 'scalar', 'exec', 'batch')][string]$Mode = 'query',
    [int]$TimeoutSec = 300
)
# 32-bit ODBC bridge for legacy Jet .mdb files (Microsoft Access Driver).
# Always invoked through 32-bit Windows PowerShell from profili_mcp.db.
#
# Modes:
#   query  - SELECT -> JSON array of objects on stdout
#   scalar - single value as JSON
#   exec   - one non-query -> {"affected": n}
#   batch  - JSON array of non-query statements read from -SqlFile, executed
#            inside one transaction -> {"affected": total}
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$ErrorActionPreference = 'Stop'

if ($Mode -eq 'batch') {
    try {
        $statements = Get-Content -Raw -Path $SqlFile -Encoding UTF8 | ConvertFrom-Json
        $conn = New-Object System.Data.Odbc.OdbcConnection("Driver={Microsoft Access Driver (*.mdb)};DBQ=$Dbq")
        $conn.Open()
        $tx = $conn.BeginTransaction()
        $total = 0
        try {
            foreach ($s in $statements) {
                $cmd = $conn.CreateCommand()
                $cmd.CommandText = [string]$s
                $cmd.CommandTimeout = $TimeoutSec
                $cmd.Transaction = $tx
                $total += $cmd.ExecuteNonQuery()
            }
            $tx.Commit()
        }
        catch {
            $tx.Rollback()
            throw
        }
        ConvertTo-Json -InputObject @{ affected = $total } -Compress
        $conn.Close()
        exit 0
    }
    catch {
        Write-Output ('BRIDGE_ERROR: ' + $_.Exception.Message)
        exit 1
    }
}

$conn = New-Object System.Data.Odbc.OdbcConnection("Driver={Microsoft Access Driver (*.mdb)};DBQ=$Dbq")
try {
    $conn.Open()
    $cmd = $conn.CreateCommand()
    $cmd.CommandText = $Sql
    $cmd.CommandTimeout = $TimeoutSec
    switch ($Mode) {
        'scalar' {
            $val = $cmd.ExecuteScalar()
            if ($null -eq $val) { 'null' } else { ConvertTo-Json -InputObject $val -Compress -Depth 3 }
        }
        'exec' {
            $n = $cmd.ExecuteNonQuery()
            $id = $null
            try {
                $cmd.CommandText = 'SELECT @@IDENTITY'
                $id = $cmd.ExecuteScalar()
            } catch { $id = $null }
            ConvertTo-Json -InputObject @{ affected = $n; identity = $id } -Compress
        }
        default {
            $reader = $cmd.ExecuteReader()
            $cols = @()
            for ($i = 0; $i -lt $reader.FieldCount; $i++) { $cols += $reader.GetName($i) }
            $rows = @()
            while ($reader.Read()) {
                $o = [ordered]@{}
                for ($i = 0; $i -lt $cols.Count; $i++) {
                    $v = $reader.GetValue($i)
                    if ($v -is [DBNull]) { $o[$cols[$i]] = $null } else { $o[$cols[$i]] = $v }
                }
                $rows += $o
            }
            $reader.Close()
            # -InputObject keeps single-row results as a JSON array (the
            # pipeline would unwrap them into {value,count} objects).
            ConvertTo-Json -InputObject @($rows) -Compress -Depth 3
        }
    }
}
catch {
    # NOTE: [Console]::OutputEncoding does not affect the error stream, which
    # would come out in the system locale (mojibake for CJK). Emit errors on
    # stdout instead, where the UTF-8 encoding set above applies.
    Write-Output ('BRIDGE_ERROR: ' + $_.Exception.Message)
    exit 1
}
finally {
    $conn.Close()
}
