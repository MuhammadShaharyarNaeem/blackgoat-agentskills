# Cloud Playbook — IaC, Pipeline, and Rollback Patterns

Minimal reference snippets per provider. Adapt names; keep the shape.

## 1. GitHub Actions — Staged Deploy Job Shape

```yaml
# .github/workflows/deploy.yml — staging → gate → production
jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - run: docker build -t $REGISTRY/app:${{ github.sha }} .   # pinned by SHA, never :latest
      - run: docker push $REGISTRY/app:${{ github.sha }}

  deploy-staging:
    needs: build
    environment: staging
    steps:
      - run: ./deploy.sh staging ${{ github.sha }}
      - run: ./smoke-test.sh https://staging.example.com/health   # readiness gate

  deploy-production:
    needs: deploy-staging
    environment: production      # GitHub environment with required reviewers = the gate
    steps:
      - run: ./deploy.sh production ${{ github.sha }}
```

Notes: cloud credentials come from OIDC federation (`aws-actions/configure-aws-credentials` / `azure/login` with federated identity) — no long-lived keys in repo secrets. Integration values (endpoints, resource names) are injected at this build/synthesis step, not looked up at runtime.

## 2. AWS — IAM Role Statement (Least Privilege)

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "OrdersServiceQueueAccess",
      "Effect": "Allow",
      "Action": ["sqs:SendMessage", "sqs:GetQueueAttributes"],
      "Resource": "arn:aws:sqs:us-east-1:123456789012:orders-events"
    },
    {
      "Sid": "OrdersServiceSecrets",
      "Effect": "Allow",
      "Action": ["secretsmanager:GetSecretValue"],
      "Resource": "arn:aws:secretsmanager:us-east-1:123456789012:secret:orders/*"
    }
  ]
}
```

BAD (never ship): `"Action": "*"`, `"Action": "s3:*"`, or `"Resource": "*"`. One role per service — services never share roles.

## 3. AWS — CloudWatch Alarms (Error Rate + p95 Latency)

```yaml
# CloudFormation/CDK-equivalent shape
OrdersApi5xxAlarm:
  Type: AWS::CloudWatch::Alarm
  Properties:
    Namespace: AWS/ApplicationELB
    MetricName: HTTPCode_Target_5XX_Count
    Dimensions: [{ Name: TargetGroup, Value: !GetAtt OrdersTargetGroup.TargetGroupFullName }]
    Statistic: Sum
    Period: 60
    EvaluationPeriods: 3
    Threshold: 10
    ComparisonOperator: GreaterThanThreshold
    AlarmActions: [!Ref OpsAlertsTopic]

OrdersApiP95LatencyAlarm:
  Type: AWS::CloudWatch::Alarm
  Properties:
    Namespace: AWS/ApplicationELB
    MetricName: TargetResponseTime
    ExtendedStatistic: p95
    Period: 60
    EvaluationPeriods: 5
    Threshold: 1.5           # seconds — set from measured baseline
    ComparisonOperator: GreaterThanThreshold
    AlarmActions: [!Ref OpsAlertsTopic]
```

## 4. Azure — Key Vault via Managed Identity (No Connection Strings)

```bicep
// bicep: app with system-assigned identity, RBAC-scoped vault access
resource app 'Microsoft.Web/sites@2023-12-01' = {
  name: 'orders-api'
  identity: { type: 'SystemAssigned' }
  properties: {
    siteConfig: {
      appSettings: [
        {
          name: 'Db--ConnectionString'
          value: '@Microsoft.KeyVault(SecretUri=https://org-kv.vault.azure.net/secrets/orders-db)'
        }
      ]
    }
  }
}

// Grant ONLY "Key Vault Secrets User" on the vault, scoped — not Contributor, not subscription-wide
resource kvRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: keyVault
  name: guid(keyVault.id, app.id, 'kv-secrets-user')
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions',
      '4633458b-17de-408a-b874-0445c86b69e6') // Key Vault Secrets User
    principalId: app.identity.principalId
  }
}
```

BAD: connection string pasted into App Service configuration, vault access policies granting `all` permissions, or a client secret used to reach the vault.

## 5. Azure — Application Insights Alert Rule

```bicep
resource failureRateAlert 'Microsoft.Insights/metricAlerts@2018-03-01' = {
  name: 'orders-api-failure-rate'
  location: 'global'
  properties: {
    severity: 2
    scopes: [appInsights.id]
    evaluationFrequency: 'PT1M'
    windowSize: 'PT5M'
    criteria: {
      'odata.type': 'Microsoft.Azure.Monitor.SingleResourceMultipleMetricCriteria'
      allOf: [{
        name: 'FailedRequests'
        metricName: 'requests/failed'
        operator: 'GreaterThan'
        threshold: 10
        timeAggregation: 'Count'
      }]
    }
    actions: [{ actionGroupId: opsActionGroup.id }]
  }
}
```

Pair with a second alert on `requests/duration` (p95, threshold from measured baseline).

## 6. Rollback Runbook

Order is always: **flag off → redeploy previous → restore**. Stop at the first step that resolves the incident.

### AWS

1. **Flag off** — disable the offending feature flag (AppConfig / your flag service). Fastest, zero-deploy.
2. **Redeploy previous** — ECS: `aws ecs update-service --task-definition <previous-revision>` (revisions are immutable and pinned by SHA). Lambda: repoint the alias to the previous version (`aws lambda update-alias --function-version <n-1>`).
3. **Restore** — data-level only, last resort: RDS point-in-time restore to a NEW instance, verify, then cut over. Never restore in place. S3 assets: CloudFront invalidation after re-uploading the previous artifact.

### Azure

1. **Flag off** — disable the flag (App Configuration feature flags).
2. **Redeploy previous** — App Service: swap the staging slot back (`az webapp deployment slot swap --slot staging --action swap` reverses the last swap), or redeploy the previous pinned image tag. Functions: redeploy previous package version.
3. **Restore** — Azure SQL point-in-time restore to a new database, verify, then repoint via the vault secret (one secret update, no config deploy — this is why connection strings live in Key Vault).

After any rollback: capture the failing version SHA, open the incident record, and report to the Orchestrator before any re-attempt.
