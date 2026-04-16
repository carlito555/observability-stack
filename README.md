# Centralized Observability Stack

AWS Managed Grafana + CloudWatch + SNS alerting, deployed via CloudFormation and managed through a GitHub Actions GitOps pipeline.

## Architecture

```
GitHub (push to main)
  └─ GitHub Actions
       ├─ Lint & Validate CloudFormation
       ├─ Deploy/Update CloudFormation Stack
       │    ├─ AWS Managed Grafana Workspace (SSO auth)
       │    ├─ Lambda Custom Resource → configures Grafana (plugins, datasource, SNS)
       │    ├─ CloudWatch Dashboards (EC2, Lambda, RDS)
       │    ├─ CloudWatch Alarms → SNS
       │    └─ SNS Topic + Email Subscription
       └─ Push Grafana Dashboard JSONs via HTTP API
```

## Project Structure

```
.
├── .github/workflows/deploy.yml    # CI/CD pipeline
├── infrastructure/template.yaml    # CloudFormation template
├── dashboards/lambda-overview.json # Grafana dashboard definitions
├── scripts/push_dashboards.py      # Dashboard sync script
├── requirements.txt                # Python dependencies
└── README.md
```

---

## Prerequisites & Setup

### 1. Enable IAM Identity Center (SSO)

AWS Managed Grafana uses IAM Identity Center for user authentication.

1. Go to **AWS Console → IAM Identity Center**
2. Click **Enable** (if not already enabled)
3. Note your **Organization ID** — you'll need it as a parameter

> **Note**: If you're in a standalone account (not part of AWS Organizations), enable IAM Identity Center first, which will auto-create an organization.

### 2. Create an OIDC Identity Provider for GitHub Actions

This allows GitHub Actions to assume an IAM role without long-lived access keys.

```bash
# Get the GitHub OIDC thumbprint (may already be auto-resolved)
aws iam create-open-id-connect-provider \
  --url https://token.actions.githubusercontent.com \
  --client-id-list sts.amazonaws.com \
  --thumbprint-list 6938fd4d98bab03faadb97b34396831e3780aea1
```

### 3. Create the GitHub Actions IAM Deploy Role

Create a role that GitHub Actions will assume via OIDC. Replace `YOUR_GITHUB_ORG` and `YOUR_REPO` below.

#### Trust Policy (`github-actions-trust-policy.json`)

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Principal": {
        "Federated": "arn:aws:iam::YOUR_ACCOUNT_ID:oidc-provider/token.actions.githubusercontent.com"
      },
      "Action": "sts:AssumeRoleWithWebIdentity",
      "Condition": {
        "StringEquals": {
          "token.actions.githubusercontent.com:aud": "sts.amazonaws.com"
        },
        "StringLike": {
          "token.actions.githubusercontent.com:sub": "repo:YOUR_GITHUB_ORG/YOUR_REPO:ref:refs/heads/main"
        }
      }
    }
  ]
}
```

#### Create the Role

```bash
aws iam create-role \
  --role-name GitHubActions-ObservabilityDeploy \
  --assume-role-policy-document file://github-actions-trust-policy.json
```

#### Attach Required Permission Policies

```bash
# CloudFormation full access
aws iam attach-role-policy \
  --role-name GitHubActions-ObservabilityDeploy \
  --policy-arn arn:aws:iam::aws:policy/AWSCloudFormationFullAccess

# IAM (for creating roles in the stack)
aws iam attach-role-policy \
  --role-name GitHubActions-ObservabilityDeploy \
  --policy-arn arn:aws:iam::aws:policy/IAMFullAccess

# Grafana
aws iam attach-role-policy \
  --role-name GitHubActions-ObservabilityDeploy \
  --policy-arn arn:aws:iam::aws:policy/AWSGrafanaAccountAdministrator

# Lambda
aws iam attach-role-policy \
  --role-name GitHubActions-ObservabilityDeploy \
  --policy-arn arn:aws:iam::aws:policy/AWSLambda_FullAccess

# SNS
aws iam attach-role-policy \
  --role-name GitHubActions-ObservabilityDeploy \
  --policy-arn arn:aws:iam::aws:policy/AmazonSNSFullAccess

# CloudWatch
aws iam attach-role-policy \
  --role-name GitHubActions-ObservabilityDeploy \
  --policy-arn arn:aws:iam::aws:policy/CloudWatchFullAccess
```

> **⚠️ Production Tip**: For a production environment, replace these broad policies with a custom least-privilege policy scoped to specific resources.

### 4. Configure GitHub Secrets

Go to your GitHub repo → **Settings → Secrets and variables → Actions** and add:

| Secret Name | Value | When Needed |
|---|---|---|
| `AWS_DEPLOY_ROLE_ARN` | `arn:aws:iam::YOUR_ACCOUNT_ID:role/GitHubActions-ObservabilityDeploy` | Before first deploy |
| `AWS_SSO_ORG_ID` | Your AWS Organizations ID (e.g. `o-abc123def4`) | Before first deploy |
| `ALERT_EMAIL` | Email address for alarm notifications | Before first deploy |
| `GRAFANA_API_KEY` | Service Account token from Grafana UI | After first deploy |

---

## Deployment

### First-Time Deploy

1. **Push to `main`** — triggers the pipeline
2. **Confirm SNS email** — check inbox for a subscription confirmation from AWS
3. **Wait for stack creation** (~5-10 min) — the Custom Resource Lambda will auto-configure Grafana plugins + CloudWatch datasource
4. **Get the Grafana URL** from CloudFormation outputs:
   ```bash
   aws cloudformation describe-stacks \
     --stack-name central-observability-stack \
     --query "Stacks[0].Outputs"
   ```
5. **Create a Grafana Service Account**:
   - Open the Grafana workspace URL
   - Go to **Administration → Service Accounts → Add Service Account**
   - Role: **Admin**
   - Create a **token** and copy it
6. **Add `GRAFANA_API_KEY`** as a GitHub Secret with the token value
7. **Re-run the pipeline** (or push a commit) — dashboards will now sync

### Adding New Dashboards

1. Create a new `.json` file in the `dashboards/` directory
2. Push to `main`
3. The pipeline will automatically upload it to Grafana under the "GitOps — Automated" folder

---

## Files Reference

| File | Description |
|---|---|
| `infrastructure/template.yaml` | CloudFormation: AMG workspace, IAM roles, SNS topic, CloudWatch dashboards/alarms, Lambda Custom Resource |
| `.github/workflows/deploy.yml` | 3-job pipeline: lint → deploy → push dashboards |
| `dashboards/lambda-overview.json` | Grafana dashboard with Lambda invocation, error, duration, and throttle panels |
| `scripts/push_dashboards.py` | Python script to sync dashboard JSONs to Grafana via the HTTP API |

## CloudFormation Parameters

| Parameter | Default | Description |
|---|---|---|
| `GrafanaWorkspaceName` | `central-observability` | Name for the AMG workspace |
| `SSOOrganizationId` | — | AWS Organizations ID |
| `AlertEmail` | — | Email for SNS alert subscription |
| `EnvironmentName` | `production` | Environment tag (`production`, `staging`, `development`) |
