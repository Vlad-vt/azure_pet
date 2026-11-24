// Hybrid SKU Matching Service — Azure infrastructure (resource-group scope, idempotent).
//
// Cost guardrails (Azure for Students, target $0–5/month):
//   * Container Apps Consumption, 0.5 vCPU / 1 GiB, minReplicas 0 (scale-to-zero), maxReplicas 2
//   * PostgreSQL Flexible Server Burstable Standard_B1ms, 32 GiB, no HA, no geo-backup, no autogrow
//   * Log Analytics PerGB2018, 30-day retention, daily ingestion cap
//   * Images come from ghcr.io (no Azure Container Registry)
targetScope = 'resourceGroup'

@description('Azure region for all resources.')
param location string = resourceGroup().location

@description('Short lowercase prefix used in resource names.')
@minLength(3)
@maxLength(12)
param namePrefix string = 'skumatch'

@description('Full container image reference, e.g. ghcr.io/<owner>/azure_pet:<sha>.')
param image string

@description('PostgreSQL administrator login.')
param pgAdminUser string = 'skumatchadmin'

@secure()
@description('PostgreSQL administrator password (from GitHub Secrets; never committed).')
param pgAdminPassword string

@description('Optional ghcr.io username for private packages (leave empty for public images).')
param ghcrUsername string = ''

@secure()
@description('Optional ghcr.io token with read:packages (leave empty for public images).')
param ghcrToken string = ''

@description('PostgreSQL SKU (must stay Burstable B1ms for the budget).')
@allowed(['Standard_B1ms'])
param pgSkuName string = 'Standard_B1ms'

@description('Daily Log Analytics ingestion cap in GB (cost guard).')
param logDailyCapGb string = '0.15'

param tags object = {
  project: 'skumatch'
  'cost-center': 'portfolio'
  'managed-by': 'bicep'
}

var suffix = uniqueString(resourceGroup().id)
var pgServerName = '${namePrefix}-pg-${suffix}'
var dbName = 'skumatch'
var useGhcrCredentials = !empty(ghcrUsername) && !empty(ghcrToken)

// ---------------------------------------------------------------- observability
resource logs 'Microsoft.OperationalInsights/workspaces@2023-09-01' = {
  name: '${namePrefix}-logs'
  location: location
  tags: tags
  properties: {
    sku: { name: 'PerGB2018' }
    retentionInDays: 30
    workspaceCapping: { dailyQuotaGb: json(logDailyCapGb) }
    features: { enableLogAccessUsingOnlyResourcePermissions: true }
  }
}

// ---------------------------------------------------------------- database
resource pg 'Microsoft.DBforPostgreSQL/flexibleServers@2024-08-01' = {
  name: pgServerName
  location: location
  tags: tags
  sku: {
    name: pgSkuName
    tier: 'Burstable'
  }
  properties: {
    version: '16'
    administratorLogin: pgAdminUser
    administratorLoginPassword: pgAdminPassword
    storage: {
      storageSizeGB: 32
      autoGrow: 'Disabled'
    }
    backup: {
      backupRetentionDays: 7
      geoRedundantBackup: 'Disabled'
    }
    highAvailability: { mode: 'Disabled' }
    network: { publicNetworkAccess: 'Enabled' }
    authConfig: {
      activeDirectoryAuth: 'Disabled'
      passwordAuth: 'Enabled'
    }
  }
}

// pgvector + pg_trgm must be allow-listed before CREATE EXTENSION (run by the migration job).
resource pgExtensions 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-08-01' = {
  parent: pg
  name: 'azure.extensions'
  properties: {
    value: 'VECTOR,PG_TRGM'
    source: 'user-override'
  }
}

resource pgDb 'Microsoft.DBforPostgreSQL/flexibleServers/databases@2024-08-01' = {
  parent: pg
  name: dbName
  properties: {
    charset: 'UTF8'
    collation: 'en_US.utf8'
  }
  dependsOn: [pgExtensions]
}

// Container Apps Consumption has no static egress IP; "Allow Azure services" (0.0.0.0) keeps the
// network free of charge. TLS is enforced and the password is a 32+ char random secret.
// See docs/adr/001-connection-pooling-b1ms.md (security trade-off section).
resource pgFirewallAzure 'Microsoft.DBforPostgreSQL/flexibleServers/firewallRules@2024-08-01' = {
  parent: pg
  name: 'AllowAzureServices'
  properties: {
    startIpAddress: '0.0.0.0'
    endIpAddress: '0.0.0.0'
  }
  dependsOn: [pgDb]
}

// ---------------------------------------------------------------- container apps
resource acaEnv 'Microsoft.App/managedEnvironments@2024-03-01' = {
  name: '${namePrefix}-env'
  location: location
  tags: tags
  properties: {
    appLogsConfiguration: {
      destination: 'log-analytics'
      logAnalyticsConfiguration: {
        customerId: logs.properties.customerId
        sharedKey: logs.listKeys().primarySharedKey
      }
    }
    workloadProfiles: [
      {
        name: 'Consumption'
        workloadProfileType: 'Consumption'
      }
    ]
    zoneRedundant: false
  }
}

var databaseUrl = 'postgresql+asyncpg://${pgAdminUser}:${uriComponent(pgAdminPassword)}@${pg.properties.fullyQualifiedDomainName}:5432/${dbName}'

var baseSecrets = [
  {
    name: 'database-url'
    value: databaseUrl
  }
]
var registrySecrets = useGhcrCredentials
  ? [
      {
        name: 'ghcr-token'
        value: ghcrToken
      }
    ]
  : []
var registries = useGhcrCredentials
  ? [
      {
        server: 'ghcr.io'
        username: ghcrUsername
        passwordSecretRef: 'ghcr-token'
      }
    ]
  : []

var commonEnv = [
  { name: 'SKUMATCH_ENV', value: 'azure' }
  { name: 'SKUMATCH_LOG_LEVEL', value: 'INFO' }
  { name: 'SKUMATCH_LOG_JSON', value: 'true' }
  { name: 'SKUMATCH_DATABASE_URL', secretRef: 'database-url' }
  { name: 'SKUMATCH_DB_SSL', value: 'true' }
  { name: 'SKUMATCH_DB_PGBOUNCER', value: 'false' }
  { name: 'SKUMATCH_DB_POOL_SIZE', value: '5' }
  { name: 'SKUMATCH_DB_MAX_OVERFLOW', value: '5' }
]

resource app 'Microsoft.App/containerApps@2024-03-01' = {
  name: '${namePrefix}-api'
  location: location
  tags: tags
  properties: {
    environmentId: acaEnv.id
    workloadProfileName: 'Consumption'
    configuration: {
      activeRevisionsMode: 'Single'
      ingress: {
        external: true
        targetPort: 8000
        transport: 'auto'
        allowInsecure: false
      }
      secrets: concat(baseSecrets, registrySecrets)
      registries: registries
    }
    template: {
      containers: [
        {
          name: 'api'
          image: image
          resources: {
            cpu: json('0.5')
            memory: '1Gi'
          }
          env: commonEnv
          probes: [
            {
              type: 'Startup'
              httpGet: { path: '/healthz', port: 8000 }
              initialDelaySeconds: 2
              periodSeconds: 2
              failureThreshold: 30
            }
            {
              type: 'Liveness'
              httpGet: { path: '/healthz', port: 8000 }
              periodSeconds: 30
              failureThreshold: 3
            }
            {
              type: 'Readiness'
              httpGet: { path: '/readyz', port: 8000 }
              periodSeconds: 10
              failureThreshold: 3
            }
          ]
        }
      ]
      scale: {
        minReplicas: 0
        maxReplicas: 2
        rules: [
          {
            name: 'http-concurrency'
            http: { metadata: { concurrentRequests: '20' } }
          }
        ]
      }
    }
  }
  dependsOn: [pgFirewallAzure]
}

// ---------------------------------------------------------------- one-off jobs (manual trigger)
// Migration gate: the deploy workflow runs this job with the new image and waits for success
// before the API revision is updated.
resource migrateJob 'Microsoft.App/jobs@2024-03-01' = {
  name: '${namePrefix}-migrate'
  location: location
  tags: tags
  properties: {
    environmentId: acaEnv.id
    workloadProfileName: 'Consumption'
    configuration: {
      triggerType: 'Manual'
      replicaTimeout: 600
      replicaRetryLimit: 1
      manualTriggerConfig: {
        parallelism: 1
        replicaCompletionCount: 1
      }
      secrets: concat(baseSecrets, registrySecrets)
      registries: registries
    }
    template: {
      containers: [
        {
          name: 'migrate'
          image: image
          command: ['alembic', 'upgrade', 'head']
          resources: {
            cpu: json('0.5')
            memory: '1Gi'
          }
          env: commonEnv
        }
      ]
    }
  }
  dependsOn: [pgFirewallAzure]
}

// Catalog ingestion (embeds 8k SKUs with the baked-in ONNX model, ~1–2 min).
resource ingestJob 'Microsoft.App/jobs@2024-03-01' = {
  name: '${namePrefix}-ingest'
  location: location
  tags: tags
  properties: {
    environmentId: acaEnv.id
    workloadProfileName: 'Consumption'
    configuration: {
      triggerType: 'Manual'
      replicaTimeout: 1800
      replicaRetryLimit: 0
      manualTriggerConfig: {
        parallelism: 1
        replicaCompletionCount: 1
      }
      secrets: concat(baseSecrets, registrySecrets)
      registries: registries
    }
    template: {
      containers: [
        {
          name: 'ingest'
          image: image
          command: ['python', 'scripts/ingest.py', '--catalog', 'data/catalog.parquet']
          resources: {
            cpu: json('1.0')
            memory: '2Gi'
          }
          env: concat(commonEnv, [
            { name: 'SKUMATCH_EMBEDDING_THREADS', value: '1' }
          ])
        }
      ]
    }
  }
  dependsOn: [pgFirewallAzure]
}

output appName string = app.name
output appFqdn string = app.properties.configuration.ingress.fqdn
output pgServerName string = pg.name
output pgHost string = pg.properties.fullyQualifiedDomainName
output environmentName string = acaEnv.name
output migrateJobName string = migrateJob.name
output ingestJobName string = ingestJob.name
output logAnalyticsName string = logs.name
