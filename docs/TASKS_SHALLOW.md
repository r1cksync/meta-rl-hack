# Full task index - 381 procedural scenarios (Round 3, shallow regime)

> Companion to [`ENV_SHALLOW.md`](ENV_SHALLOW.md). Lists every one of the 381 procedural sim scenarios used by the Phi-3.5-mini PPO+LoRA Kaggle run, grouped by tier and sorted by id. Each row carries the title, target score, max steps, and the **canonical correct action chain** the agent has to discover. The action ids on each row are the same simulator action ids documented in [`ENV_SHALLOW.md` section 3](ENV_SHALLOW.md#3--action-space-full-simulator-surface).

## Category index (49 categories across 3 tiers)

| Tier | Category prefix | Scenarios | What it simulates |
|---|---|---:|---|
| easy | `sim_easy_ddb_throttle_*` | 20 | DynamoDB throttling (per-service capacity hit) |
| easy | `sim_easy_kms_disabled_*` | 20 | KMS key disabled / decrypt failure |
| easy | `sim_easy_lambda_throttle_*` | 20 | Lambda concurrency throttling |
| easy | `sim_easy_secret_rotation_*` | 20 | Secrets Manager rotation regression |
| easy | `sim_easy_sqs_dlq_*` | 20 | SQS DLQ growth |
| easy | `sim_easy_ssm_drift_*` | 20 | SSM Parameter Store drift |
| easy | `sim_gen_app_leak_api_gateway_*` | 4 | App memory leak - api-gateway |
| easy | `sim_gen_app_leak_auth_*` | 4 | App memory leak - auth-service |
| easy | `sim_gen_app_leak_catalog_*` | 4 | App memory leak - catalog-service |
| easy | `sim_gen_app_leak_checkout_*` | 4 | App memory leak - checkout-frontend |
| easy | `sim_gen_app_leak_frontend_*` | 4 | App memory leak - frontend |
| easy | `sim_gen_app_leak_inventory_*` | 4 | App memory leak - inventory-service |
| easy | `sim_gen_app_leak_payments_*` | 4 | App memory leak - payments-api |
| easy | `sim_gen_cache_warm_search_index_*` | 4 | Cold cache - search index warmup |
| easy | `sim_gen_cache_warm_session_cache_*` | 4 | Cold cache - session cache warmup |
| medium | `sim_med_eb_lambda_*` | 15 | EventBridge -> Lambda silent drop |
| medium | `sim_med_kms_lambda_*` | 15 | KMS rotation breaks Lambda decrypt |
| medium | `sim_med_lambda_secret_*` | 15 | Lambda -> secret rotation cascade |
| medium | `sim_med_sfn_lambda_*` | 15 | Step Functions -> Lambda failure |
| medium | `sim_gen_cache_warm_search_index_*` | 8 | Cold cache - search index warmup |
| medium | `sim_gen_cache_warm_session_cache_*` | 8 | Cold cache - session cache warmup |
| medium | `sim_gen_redherring_auth_*` | 4 | Red-herring - auth distractor |
| medium | `sim_gen_redherring_catalog_*` | 4 | Red-herring - catalog distractor |
| medium | `sim_gen_redherring_checkout_*` | 4 | Red-herring - checkout distractor |
| medium | `sim_gen_redherring_inventory_*` | 4 | Red-herring - inventory distractor |
| medium | `sim_gen_redherring_payments_*` | 4 | Red-herring - payments distractor |
| medium | `sim_gen_peak_api_gateway_*` | 3 | Peak-load surge - api-gateway |
| medium | `sim_gen_peak_auth_*` | 3 | Peak-load surge - auth-service |
| medium | `sim_gen_peak_catalog_*` | 3 | Peak-load surge - catalog-service |
| medium | `sim_gen_peak_cdn_*` | 3 | Peak-load surge - cdn |
| medium | `sim_gen_peak_checkout_*` | 3 | Peak-load surge - checkout-frontend |
| medium | `sim_gen_peak_frontend_*` | 3 | Peak-load surge - frontend |
| medium | `sim_gen_app_leak_api_gateway_*` | 2 | App memory leak - api-gateway |
| medium | `sim_gen_app_leak_auth_*` | 2 | App memory leak - auth-service |
| medium | `sim_gen_app_leak_catalog_*` | 2 | App memory leak - catalog-service |
| medium | `sim_gen_app_leak_checkout_*` | 2 | App memory leak - checkout-frontend |
| medium | `sim_gen_app_leak_frontend_*` | 2 | App memory leak - frontend |
| medium | `sim_gen_app_leak_inventory_*` | 2 | App memory leak - inventory-service |
| medium | `sim_gen_app_leak_payments_*` | 2 | App memory leak - payments-api |
| hard | `sim_gen_db_duel_orders_db_*` | 12 | DB duel - orders DB connection storm |
| hard | `sim_gen_db_duel_users_db_*` | 12 | DB duel - users DB connection storm |
| hard | `sim_hard_apigw_chain_*` | 10 | API Gateway 5xx multi-hop chain |
| hard | `sim_hard_ddb_chain_*` | 10 | DynamoDB throttle multi-hop chain |
| hard | `sim_hard_iam_chain_*` | 10 | IAM drift multi-hop chain |
| hard | `sim_gen_cascade_catalog_db_*` | 6 | Cascading failure via catalog DB |
| hard | `sim_gen_cascade_inventory_db_*` | 6 | Cascading failure via inventory DB |
| hard | `sim_gen_cascade_orders_db_*` | 6 | Cascading failure via orders DB |
| hard | `sim_gen_cascade_payments_db_*` | 6 | Cascading failure via payments DB |
| hard | `sim_gen_cascade_users_db_*` | 6 | Cascading failure via users DB |
| hard | `sim_gen_restore_catalog_db_*` | 2 | PITR restore - catalog DB |
| hard | `sim_gen_restore_inventory_db_*` | 2 | PITR restore - inventory DB |
| hard | `sim_gen_restore_orders_db_*` | 2 | PITR restore - orders DB |
| hard | `sim_gen_restore_payments_db_*` | 2 | PITR restore - payments DB |
| hard | `sim_advanced_cascade_users_db_*` | 1 | Advanced - users DB cascade (saboteur reinjects) |
| hard | `sim_advanced_runbook_trap_postgres_*` | 1 | Advanced - Runbook Trap (postgres) |
| hard | `sim_advanced_saboteur_duel_*` | 1 | Advanced - Saboteur duel (failover loop) |
| hard | `sim_advanced_slack_redherring_*` | 1 | Advanced - Slack Red Herring (CEO panic vs reality) |
| hard | `sim_advanced_trolley_orders_db_*` | 1 | Advanced - Trolley Problem (orders DB partial sacrifice) |

**Total: 381 scenarios** (156 easy + 128 medium + 97 hard).

## Easy tier - 156 scenarios

| # | ID | Title | Target | Max steps | Correct chain |
|---:|---|---|---:|---:|---|
| 1 | `sim_easy_ddb_throttle_101` | checkout DynamoDB throttling | 0.55 | 16 | dynamodb.describe -> dynamodb.scale |
| 2 | `sim_easy_ddb_throttle_102` | orders DynamoDB throttling | 0.55 | 16 | dynamodb.describe -> dynamodb.scale |
| 3 | `sim_easy_ddb_throttle_103` | inventory DynamoDB throttling | 0.55 | 16 | dynamodb.describe -> dynamodb.scale |
| 4 | `sim_easy_ddb_throttle_104` | payments DynamoDB throttling | 0.55 | 16 | dynamodb.describe -> dynamodb.scale |
| 5 | `sim_easy_ddb_throttle_105` | search DynamoDB throttling | 0.55 | 16 | dynamodb.describe -> dynamodb.scale |
| 6 | `sim_easy_ddb_throttle_106` | recommendations DynamoDB throttling | 0.55 | 16 | dynamodb.describe -> dynamodb.scale |
| 7 | `sim_easy_ddb_throttle_107` | auth DynamoDB throttling | 0.55 | 16 | dynamodb.describe -> dynamodb.scale |
| 8 | `sim_easy_ddb_throttle_108` | billing DynamoDB throttling | 0.55 | 16 | dynamodb.describe -> dynamodb.scale |
| 9 | `sim_easy_ddb_throttle_109` | shipping DynamoDB throttling | 0.55 | 16 | dynamodb.describe -> dynamodb.scale |
| 10 | `sim_easy_ddb_throttle_110` | notifications DynamoDB throttling | 0.55 | 16 | dynamodb.describe -> dynamodb.scale |
| 11 | `sim_easy_ddb_throttle_111` | reviews DynamoDB throttling | 0.55 | 16 | dynamodb.describe -> dynamodb.scale |
| 12 | `sim_easy_ddb_throttle_112` | catalog DynamoDB throttling | 0.55 | 16 | dynamodb.describe -> dynamodb.scale |
| 13 | `sim_easy_ddb_throttle_113` | fulfillment DynamoDB throttling | 0.55 | 16 | dynamodb.describe -> dynamodb.scale |
| 14 | `sim_easy_ddb_throttle_114` | telemetry DynamoDB throttling | 0.55 | 16 | dynamodb.describe -> dynamodb.scale |
| 15 | `sim_easy_ddb_throttle_115` | analytics DynamoDB throttling | 0.55 | 16 | dynamodb.describe -> dynamodb.scale |
| 16 | `sim_easy_ddb_throttle_116` | userprofile DynamoDB throttling | 0.55 | 16 | dynamodb.describe -> dynamodb.scale |
| 17 | `sim_easy_ddb_throttle_117` | cart DynamoDB throttling | 0.55 | 16 | dynamodb.describe -> dynamodb.scale |
| 18 | `sim_easy_ddb_throttle_118` | pricing DynamoDB throttling | 0.55 | 16 | dynamodb.describe -> dynamodb.scale |
| 19 | `sim_easy_ddb_throttle_119` | promotions DynamoDB throttling | 0.55 | 16 | dynamodb.describe -> dynamodb.scale |
| 20 | `sim_easy_ddb_throttle_120` | media DynamoDB throttling | 0.55 | 16 | dynamodb.describe -> dynamodb.scale |
| 21 | `sim_easy_kms_disabled_061` | checkout KMS key disabled | 0.55 | 16 | kms.describe -> kms.encrypt -> kms.enable -> kms.encrypt |
| 22 | `sim_easy_kms_disabled_062` | orders KMS key disabled | 0.55 | 16 | kms.describe -> kms.encrypt -> kms.enable -> kms.encrypt |
| 23 | `sim_easy_kms_disabled_063` | inventory KMS key disabled | 0.55 | 16 | kms.describe -> kms.encrypt -> kms.enable -> kms.encrypt |
| 24 | `sim_easy_kms_disabled_064` | payments KMS key disabled | 0.55 | 16 | kms.describe -> kms.encrypt -> kms.enable -> kms.encrypt |
| 25 | `sim_easy_kms_disabled_065` | search KMS key disabled | 0.55 | 16 | kms.describe -> kms.encrypt -> kms.enable -> kms.encrypt |
| 26 | `sim_easy_kms_disabled_066` | recommendations KMS key disabled | 0.55 | 16 | kms.describe -> kms.encrypt -> kms.enable -> kms.encrypt |
| 27 | `sim_easy_kms_disabled_067` | auth KMS key disabled | 0.55 | 16 | kms.describe -> kms.encrypt -> kms.enable -> kms.encrypt |
| 28 | `sim_easy_kms_disabled_068` | billing KMS key disabled | 0.55 | 16 | kms.describe -> kms.encrypt -> kms.enable -> kms.encrypt |
| 29 | `sim_easy_kms_disabled_069` | shipping KMS key disabled | 0.55 | 16 | kms.describe -> kms.encrypt -> kms.enable -> kms.encrypt |
| 30 | `sim_easy_kms_disabled_070` | notifications KMS key disabled | 0.55 | 16 | kms.describe -> kms.encrypt -> kms.enable -> kms.encrypt |
| 31 | `sim_easy_kms_disabled_071` | reviews KMS key disabled | 0.55 | 16 | kms.describe -> kms.encrypt -> kms.enable -> kms.encrypt |
| 32 | `sim_easy_kms_disabled_072` | catalog KMS key disabled | 0.55 | 16 | kms.describe -> kms.encrypt -> kms.enable -> kms.encrypt |
| 33 | `sim_easy_kms_disabled_073` | fulfillment KMS key disabled | 0.55 | 16 | kms.describe -> kms.encrypt -> kms.enable -> kms.encrypt |
| 34 | `sim_easy_kms_disabled_074` | telemetry KMS key disabled | 0.55 | 16 | kms.describe -> kms.encrypt -> kms.enable -> kms.encrypt |
| 35 | `sim_easy_kms_disabled_075` | analytics KMS key disabled | 0.55 | 16 | kms.describe -> kms.encrypt -> kms.enable -> kms.encrypt |
| 36 | `sim_easy_kms_disabled_076` | userprofile KMS key disabled | 0.55 | 16 | kms.describe -> kms.encrypt -> kms.enable -> kms.encrypt |
| 37 | `sim_easy_kms_disabled_077` | cart KMS key disabled | 0.55 | 16 | kms.describe -> kms.encrypt -> kms.enable -> kms.encrypt |
| 38 | `sim_easy_kms_disabled_078` | pricing KMS key disabled | 0.55 | 16 | kms.describe -> kms.encrypt -> kms.enable -> kms.encrypt |
| 39 | `sim_easy_kms_disabled_079` | promotions KMS key disabled | 0.55 | 16 | kms.describe -> kms.encrypt -> kms.enable -> kms.encrypt |
| 40 | `sim_easy_kms_disabled_080` | media KMS key disabled | 0.55 | 16 | kms.describe -> kms.encrypt -> kms.enable -> kms.encrypt |
| 41 | `sim_easy_lambda_throttle_001` | checkout Lambda throttling | 0.55 | 16 | lambda.describe -> lambda.invoke -> lambda.scale -> lambda.invoke |
| 42 | `sim_easy_lambda_throttle_002` | orders Lambda throttling | 0.55 | 16 | lambda.describe -> lambda.invoke -> lambda.scale -> lambda.invoke |
| 43 | `sim_easy_lambda_throttle_003` | inventory Lambda throttling | 0.55 | 16 | lambda.describe -> lambda.invoke -> lambda.scale -> lambda.invoke |
| 44 | `sim_easy_lambda_throttle_004` | payments Lambda throttling | 0.55 | 16 | lambda.describe -> lambda.invoke -> lambda.scale -> lambda.invoke |
| 45 | `sim_easy_lambda_throttle_005` | search Lambda throttling | 0.55 | 16 | lambda.describe -> lambda.invoke -> lambda.scale -> lambda.invoke |
| 46 | `sim_easy_lambda_throttle_006` | recommendations Lambda throttling | 0.55 | 16 | lambda.describe -> lambda.invoke -> lambda.scale -> lambda.invoke |
| 47 | `sim_easy_lambda_throttle_007` | auth Lambda throttling | 0.55 | 16 | lambda.describe -> lambda.invoke -> lambda.scale -> lambda.invoke |
| 48 | `sim_easy_lambda_throttle_008` | billing Lambda throttling | 0.55 | 16 | lambda.describe -> lambda.invoke -> lambda.scale -> lambda.invoke |
| 49 | `sim_easy_lambda_throttle_009` | shipping Lambda throttling | 0.55 | 16 | lambda.describe -> lambda.invoke -> lambda.scale -> lambda.invoke |
| 50 | `sim_easy_lambda_throttle_010` | notifications Lambda throttling | 0.55 | 16 | lambda.describe -> lambda.invoke -> lambda.scale -> lambda.invoke |
| 51 | `sim_easy_lambda_throttle_011` | reviews Lambda throttling | 0.55 | 16 | lambda.describe -> lambda.invoke -> lambda.scale -> lambda.invoke |
| 52 | `sim_easy_lambda_throttle_012` | catalog Lambda throttling | 0.55 | 16 | lambda.describe -> lambda.invoke -> lambda.scale -> lambda.invoke |
| 53 | `sim_easy_lambda_throttle_013` | fulfillment Lambda throttling | 0.55 | 16 | lambda.describe -> lambda.invoke -> lambda.scale -> lambda.invoke |
| 54 | `sim_easy_lambda_throttle_014` | telemetry Lambda throttling | 0.55 | 16 | lambda.describe -> lambda.invoke -> lambda.scale -> lambda.invoke |
| 55 | `sim_easy_lambda_throttle_015` | analytics Lambda throttling | 0.55 | 16 | lambda.describe -> lambda.invoke -> lambda.scale -> lambda.invoke |
| 56 | `sim_easy_lambda_throttle_016` | userprofile Lambda throttling | 0.55 | 16 | lambda.describe -> lambda.invoke -> lambda.scale -> lambda.invoke |
| 57 | `sim_easy_lambda_throttle_017` | cart Lambda throttling | 0.55 | 16 | lambda.describe -> lambda.invoke -> lambda.scale -> lambda.invoke |
| 58 | `sim_easy_lambda_throttle_018` | pricing Lambda throttling | 0.55 | 16 | lambda.describe -> lambda.invoke -> lambda.scale -> lambda.invoke |
| 59 | `sim_easy_lambda_throttle_019` | promotions Lambda throttling | 0.55 | 16 | lambda.describe -> lambda.invoke -> lambda.scale -> lambda.invoke |
| 60 | `sim_easy_lambda_throttle_020` | media Lambda throttling | 0.55 | 16 | lambda.describe -> lambda.invoke -> lambda.scale -> lambda.invoke |
| 61 | `sim_easy_secret_rotation_041` | checkout secret rotation overdue | 0.55 | 16 | secretsmanager.describe -> secretsmanager.rotate |
| 62 | `sim_easy_secret_rotation_042` | orders secret rotation overdue | 0.55 | 16 | secretsmanager.describe -> secretsmanager.rotate |
| 63 | `sim_easy_secret_rotation_043` | inventory secret rotation overdue | 0.55 | 16 | secretsmanager.describe -> secretsmanager.rotate |
| 64 | `sim_easy_secret_rotation_044` | payments secret rotation overdue | 0.55 | 16 | secretsmanager.describe -> secretsmanager.rotate |
| 65 | `sim_easy_secret_rotation_045` | search secret rotation overdue | 0.55 | 16 | secretsmanager.describe -> secretsmanager.rotate |
| 66 | `sim_easy_secret_rotation_046` | recommendations secret rotation overdue | 0.55 | 16 | secretsmanager.describe -> secretsmanager.rotate |
| 67 | `sim_easy_secret_rotation_047` | auth secret rotation overdue | 0.55 | 16 | secretsmanager.describe -> secretsmanager.rotate |
| 68 | `sim_easy_secret_rotation_048` | billing secret rotation overdue | 0.55 | 16 | secretsmanager.describe -> secretsmanager.rotate |
| 69 | `sim_easy_secret_rotation_049` | shipping secret rotation overdue | 0.55 | 16 | secretsmanager.describe -> secretsmanager.rotate |
| 70 | `sim_easy_secret_rotation_050` | notifications secret rotation overdue | 0.55 | 16 | secretsmanager.describe -> secretsmanager.rotate |
| 71 | `sim_easy_secret_rotation_051` | reviews secret rotation overdue | 0.55 | 16 | secretsmanager.describe -> secretsmanager.rotate |
| 72 | `sim_easy_secret_rotation_052` | catalog secret rotation overdue | 0.55 | 16 | secretsmanager.describe -> secretsmanager.rotate |
| 73 | `sim_easy_secret_rotation_053` | fulfillment secret rotation overdue | 0.55 | 16 | secretsmanager.describe -> secretsmanager.rotate |
| 74 | `sim_easy_secret_rotation_054` | telemetry secret rotation overdue | 0.55 | 16 | secretsmanager.describe -> secretsmanager.rotate |
| 75 | `sim_easy_secret_rotation_055` | analytics secret rotation overdue | 0.55 | 16 | secretsmanager.describe -> secretsmanager.rotate |
| 76 | `sim_easy_secret_rotation_056` | userprofile secret rotation overdue | 0.55 | 16 | secretsmanager.describe -> secretsmanager.rotate |
| 77 | `sim_easy_secret_rotation_057` | cart secret rotation overdue | 0.55 | 16 | secretsmanager.describe -> secretsmanager.rotate |
| 78 | `sim_easy_secret_rotation_058` | pricing secret rotation overdue | 0.55 | 16 | secretsmanager.describe -> secretsmanager.rotate |
| 79 | `sim_easy_secret_rotation_059` | promotions secret rotation overdue | 0.55 | 16 | secretsmanager.describe -> secretsmanager.rotate |
| 80 | `sim_easy_secret_rotation_060` | media secret rotation overdue | 0.55 | 16 | secretsmanager.describe -> secretsmanager.rotate |
| 81 | `sim_easy_sqs_dlq_021` | checkout DLQ depth growing | 0.55 | 16 | sqs.describe -> sqs.receive -> sqs.purge |
| 82 | `sim_easy_sqs_dlq_022` | orders DLQ depth growing | 0.55 | 16 | sqs.describe -> sqs.receive -> sqs.purge |
| 83 | `sim_easy_sqs_dlq_023` | inventory DLQ depth growing | 0.55 | 16 | sqs.describe -> sqs.receive -> sqs.purge |
| 84 | `sim_easy_sqs_dlq_024` | payments DLQ depth growing | 0.55 | 16 | sqs.describe -> sqs.receive -> sqs.purge |
| 85 | `sim_easy_sqs_dlq_025` | search DLQ depth growing | 0.55 | 16 | sqs.describe -> sqs.receive -> sqs.purge |
| 86 | `sim_easy_sqs_dlq_026` | recommendations DLQ depth growing | 0.55 | 16 | sqs.describe -> sqs.receive -> sqs.purge |
| 87 | `sim_easy_sqs_dlq_027` | auth DLQ depth growing | 0.55 | 16 | sqs.describe -> sqs.receive -> sqs.purge |
| 88 | `sim_easy_sqs_dlq_028` | billing DLQ depth growing | 0.55 | 16 | sqs.describe -> sqs.receive -> sqs.purge |
| 89 | `sim_easy_sqs_dlq_029` | shipping DLQ depth growing | 0.55 | 16 | sqs.describe -> sqs.receive -> sqs.purge |
| 90 | `sim_easy_sqs_dlq_030` | notifications DLQ depth growing | 0.55 | 16 | sqs.describe -> sqs.receive -> sqs.purge |
| 91 | `sim_easy_sqs_dlq_031` | reviews DLQ depth growing | 0.55 | 16 | sqs.describe -> sqs.receive -> sqs.purge |
| 92 | `sim_easy_sqs_dlq_032` | catalog DLQ depth growing | 0.55 | 16 | sqs.describe -> sqs.receive -> sqs.purge |
| 93 | `sim_easy_sqs_dlq_033` | fulfillment DLQ depth growing | 0.55 | 16 | sqs.describe -> sqs.receive -> sqs.purge |
| 94 | `sim_easy_sqs_dlq_034` | telemetry DLQ depth growing | 0.55 | 16 | sqs.describe -> sqs.receive -> sqs.purge |
| 95 | `sim_easy_sqs_dlq_035` | analytics DLQ depth growing | 0.55 | 16 | sqs.describe -> sqs.receive -> sqs.purge |
| 96 | `sim_easy_sqs_dlq_036` | userprofile DLQ depth growing | 0.55 | 16 | sqs.describe -> sqs.receive -> sqs.purge |
| 97 | `sim_easy_sqs_dlq_037` | cart DLQ depth growing | 0.55 | 16 | sqs.describe -> sqs.receive -> sqs.purge |
| 98 | `sim_easy_sqs_dlq_038` | pricing DLQ depth growing | 0.55 | 16 | sqs.describe -> sqs.receive -> sqs.purge |
| 99 | `sim_easy_sqs_dlq_039` | promotions DLQ depth growing | 0.55 | 16 | sqs.describe -> sqs.receive -> sqs.purge |
| 100 | `sim_easy_sqs_dlq_040` | media DLQ depth growing | 0.55 | 16 | sqs.describe -> sqs.receive -> sqs.purge |
| 101 | `sim_easy_ssm_drift_081` | checkout pool size dropped | 0.55 | 16 | ssm.describe -> ssm.diff_versions -> ssm.rollback |
| 102 | `sim_easy_ssm_drift_082` | orders pool size dropped | 0.55 | 16 | ssm.describe -> ssm.diff_versions -> ssm.rollback |
| 103 | `sim_easy_ssm_drift_083` | inventory pool size dropped | 0.55 | 16 | ssm.describe -> ssm.diff_versions -> ssm.rollback |
| 104 | `sim_easy_ssm_drift_084` | payments pool size dropped | 0.55 | 16 | ssm.describe -> ssm.diff_versions -> ssm.rollback |
| 105 | `sim_easy_ssm_drift_085` | search pool size dropped | 0.55 | 16 | ssm.describe -> ssm.diff_versions -> ssm.rollback |
| 106 | `sim_easy_ssm_drift_086` | recommendations pool size dropped | 0.55 | 16 | ssm.describe -> ssm.diff_versions -> ssm.rollback |
| 107 | `sim_easy_ssm_drift_087` | auth pool size dropped | 0.55 | 16 | ssm.describe -> ssm.diff_versions -> ssm.rollback |
| 108 | `sim_easy_ssm_drift_088` | billing pool size dropped | 0.55 | 16 | ssm.describe -> ssm.diff_versions -> ssm.rollback |
| 109 | `sim_easy_ssm_drift_089` | shipping pool size dropped | 0.55 | 16 | ssm.describe -> ssm.diff_versions -> ssm.rollback |
| 110 | `sim_easy_ssm_drift_090` | notifications pool size dropped | 0.55 | 16 | ssm.describe -> ssm.diff_versions -> ssm.rollback |
| 111 | `sim_easy_ssm_drift_091` | reviews pool size dropped | 0.55 | 16 | ssm.describe -> ssm.diff_versions -> ssm.rollback |
| 112 | `sim_easy_ssm_drift_092` | catalog pool size dropped | 0.55 | 16 | ssm.describe -> ssm.diff_versions -> ssm.rollback |
| 113 | `sim_easy_ssm_drift_093` | fulfillment pool size dropped | 0.55 | 16 | ssm.describe -> ssm.diff_versions -> ssm.rollback |
| 114 | `sim_easy_ssm_drift_094` | telemetry pool size dropped | 0.55 | 16 | ssm.describe -> ssm.diff_versions -> ssm.rollback |
| 115 | `sim_easy_ssm_drift_095` | analytics pool size dropped | 0.55 | 16 | ssm.describe -> ssm.diff_versions -> ssm.rollback |
| 116 | `sim_easy_ssm_drift_096` | userprofile pool size dropped | 0.55 | 16 | ssm.describe -> ssm.diff_versions -> ssm.rollback |
| 117 | `sim_easy_ssm_drift_097` | cart pool size dropped | 0.55 | 16 | ssm.describe -> ssm.diff_versions -> ssm.rollback |
| 118 | `sim_easy_ssm_drift_098` | pricing pool size dropped | 0.55 | 16 | ssm.describe -> ssm.diff_versions -> ssm.rollback |
| 119 | `sim_easy_ssm_drift_099` | promotions pool size dropped | 0.55 | 16 | ssm.describe -> ssm.diff_versions -> ssm.rollback |
| 120 | `sim_easy_ssm_drift_100` | media pool size dropped | 0.55 | 16 | ssm.describe -> ssm.diff_versions -> ssm.rollback |
| 121 | `sim_gen_app_leak_api_gateway_037` | Memory leak in api_gateway (aggro=0.4) | 0.55 | 16 | platform.read_slack -> platform.get_logs -> platform.get_metrics -> platform.pause_health_checks -> platform.capture_memory_dump -> platform.rollback_deployment -> platform.resume_health_checks |
| 122 | `sim_gen_app_leak_api_gateway_038` | Memory leak in api_gateway (aggro=0.4) | 0.55 | 16 | platform.read_slack -> platform.get_logs -> platform.get_metrics -> platform.pause_health_checks -> platform.capture_memory_dump -> platform.rollback_deployment -> platform.resume_health_checks |
| 123 | `sim_gen_app_leak_api_gateway_039` | Memory leak in api_gateway (aggro=0.6) | 0.55 | 16 | platform.read_slack -> platform.get_logs -> platform.get_metrics -> platform.pause_health_checks -> platform.capture_memory_dump -> platform.rollback_deployment -> platform.resume_health_checks |
| 124 | `sim_gen_app_leak_api_gateway_040` | Memory leak in api_gateway (aggro=0.6) | 0.55 | 16 | platform.read_slack -> platform.get_logs -> platform.get_metrics -> platform.pause_health_checks -> platform.capture_memory_dump -> platform.rollback_deployment -> platform.resume_health_checks |
| 125 | `sim_gen_app_leak_auth_001` | Memory leak in auth (aggro=0.4) | 0.55 | 16 | platform.read_slack -> platform.get_logs -> platform.get_metrics -> platform.pause_health_checks -> platform.capture_memory_dump -> platform.rollback_deployment -> platform.resume_health_checks |
| 126 | `sim_gen_app_leak_auth_002` | Memory leak in auth (aggro=0.4) | 0.55 | 16 | platform.read_slack -> platform.get_logs -> platform.get_metrics -> platform.pause_health_checks -> platform.capture_memory_dump -> platform.rollback_deployment -> platform.resume_health_checks |
| 127 | `sim_gen_app_leak_auth_003` | Memory leak in auth (aggro=0.6) | 0.55 | 16 | platform.read_slack -> platform.get_logs -> platform.get_metrics -> platform.pause_health_checks -> platform.capture_memory_dump -> platform.rollback_deployment -> platform.resume_health_checks |
| 128 | `sim_gen_app_leak_auth_004` | Memory leak in auth (aggro=0.6) | 0.55 | 16 | platform.read_slack -> platform.get_logs -> platform.get_metrics -> platform.pause_health_checks -> platform.capture_memory_dump -> platform.rollback_deployment -> platform.resume_health_checks |
| 129 | `sim_gen_app_leak_catalog_013` | Memory leak in catalog (aggro=0.4) | 0.55 | 16 | platform.read_slack -> platform.get_logs -> platform.get_metrics -> platform.pause_health_checks -> platform.capture_memory_dump -> platform.rollback_deployment -> platform.resume_health_checks |
| 130 | `sim_gen_app_leak_catalog_014` | Memory leak in catalog (aggro=0.4) | 0.55 | 16 | platform.read_slack -> platform.get_logs -> platform.get_metrics -> platform.pause_health_checks -> platform.capture_memory_dump -> platform.rollback_deployment -> platform.resume_health_checks |
| 131 | `sim_gen_app_leak_catalog_015` | Memory leak in catalog (aggro=0.6) | 0.55 | 16 | platform.read_slack -> platform.get_logs -> platform.get_metrics -> platform.pause_health_checks -> platform.capture_memory_dump -> platform.rollback_deployment -> platform.resume_health_checks |
| 132 | `sim_gen_app_leak_catalog_016` | Memory leak in catalog (aggro=0.6) | 0.55 | 16 | platform.read_slack -> platform.get_logs -> platform.get_metrics -> platform.pause_health_checks -> platform.capture_memory_dump -> platform.rollback_deployment -> platform.resume_health_checks |
| 133 | `sim_gen_app_leak_checkout_007` | Memory leak in checkout (aggro=0.4) | 0.55 | 16 | platform.read_slack -> platform.get_logs -> platform.get_metrics -> platform.pause_health_checks -> platform.capture_memory_dump -> platform.rollback_deployment -> platform.resume_health_checks |
| 134 | `sim_gen_app_leak_checkout_008` | Memory leak in checkout (aggro=0.4) | 0.55 | 16 | platform.read_slack -> platform.get_logs -> platform.get_metrics -> platform.pause_health_checks -> platform.capture_memory_dump -> platform.rollback_deployment -> platform.resume_health_checks |
| 135 | `sim_gen_app_leak_checkout_009` | Memory leak in checkout (aggro=0.6) | 0.55 | 16 | platform.read_slack -> platform.get_logs -> platform.get_metrics -> platform.pause_health_checks -> platform.capture_memory_dump -> platform.rollback_deployment -> platform.resume_health_checks |
| 136 | `sim_gen_app_leak_checkout_010` | Memory leak in checkout (aggro=0.6) | 0.55 | 16 | platform.read_slack -> platform.get_logs -> platform.get_metrics -> platform.pause_health_checks -> platform.capture_memory_dump -> platform.rollback_deployment -> platform.resume_health_checks |
| 137 | `sim_gen_app_leak_frontend_031` | Memory leak in frontend (aggro=0.4) | 0.55 | 16 | platform.read_slack -> platform.get_logs -> platform.get_metrics -> platform.pause_health_checks -> platform.capture_memory_dump -> platform.rollback_deployment -> platform.resume_health_checks |
| 138 | `sim_gen_app_leak_frontend_032` | Memory leak in frontend (aggro=0.4) | 0.55 | 16 | platform.read_slack -> platform.get_logs -> platform.get_metrics -> platform.pause_health_checks -> platform.capture_memory_dump -> platform.rollback_deployment -> platform.resume_health_checks |
| 139 | `sim_gen_app_leak_frontend_033` | Memory leak in frontend (aggro=0.6) | 0.55 | 16 | platform.read_slack -> platform.get_logs -> platform.get_metrics -> platform.pause_health_checks -> platform.capture_memory_dump -> platform.rollback_deployment -> platform.resume_health_checks |
| 140 | `sim_gen_app_leak_frontend_034` | Memory leak in frontend (aggro=0.6) | 0.55 | 16 | platform.read_slack -> platform.get_logs -> platform.get_metrics -> platform.pause_health_checks -> platform.capture_memory_dump -> platform.rollback_deployment -> platform.resume_health_checks |
| 141 | `sim_gen_app_leak_inventory_025` | Memory leak in inventory (aggro=0.4) | 0.55 | 16 | platform.read_slack -> platform.get_logs -> platform.get_metrics -> platform.pause_health_checks -> platform.capture_memory_dump -> platform.rollback_deployment -> platform.resume_health_checks |
| 142 | `sim_gen_app_leak_inventory_026` | Memory leak in inventory (aggro=0.4) | 0.55 | 16 | platform.read_slack -> platform.get_logs -> platform.get_metrics -> platform.pause_health_checks -> platform.capture_memory_dump -> platform.rollback_deployment -> platform.resume_health_checks |
| 143 | `sim_gen_app_leak_inventory_027` | Memory leak in inventory (aggro=0.6) | 0.55 | 16 | platform.read_slack -> platform.get_logs -> platform.get_metrics -> platform.pause_health_checks -> platform.capture_memory_dump -> platform.rollback_deployment -> platform.resume_health_checks |
| 144 | `sim_gen_app_leak_inventory_028` | Memory leak in inventory (aggro=0.6) | 0.55 | 16 | platform.read_slack -> platform.get_logs -> platform.get_metrics -> platform.pause_health_checks -> platform.capture_memory_dump -> platform.rollback_deployment -> platform.resume_health_checks |
| 145 | `sim_gen_app_leak_payments_019` | Memory leak in payments (aggro=0.4) | 0.55 | 16 | platform.read_slack -> platform.get_logs -> platform.get_metrics -> platform.pause_health_checks -> platform.capture_memory_dump -> platform.rollback_deployment -> platform.resume_health_checks |
| 146 | `sim_gen_app_leak_payments_020` | Memory leak in payments (aggro=0.4) | 0.55 | 16 | platform.read_slack -> platform.get_logs -> platform.get_metrics -> platform.pause_health_checks -> platform.capture_memory_dump -> platform.rollback_deployment -> platform.resume_health_checks |
| 147 | `sim_gen_app_leak_payments_021` | Memory leak in payments (aggro=0.6) | 0.55 | 16 | platform.read_slack -> platform.get_logs -> platform.get_metrics -> platform.pause_health_checks -> platform.capture_memory_dump -> platform.rollback_deployment -> platform.resume_health_checks |
| 148 | `sim_gen_app_leak_payments_022` | Memory leak in payments (aggro=0.6) | 0.55 | 16 | platform.read_slack -> platform.get_logs -> platform.get_metrics -> platform.pause_health_checks -> platform.capture_memory_dump -> platform.rollback_deployment -> platform.resume_health_checks |
| 149 | `sim_gen_cache_warm_search_index_013` | Cache outage on search_index during 0.5x peak | 0.6 | 14 | platform.read_slack -> platform.get_traffic -> platform.get_logs -> platform.search_runbook -> platform.enable_request_coalescing -> platform.warm_cache |
| 150 | `sim_gen_cache_warm_search_index_016` | Cache outage on search_index during 0.5x peak | 0.6 | 14 | platform.read_slack -> platform.get_traffic -> platform.get_logs -> platform.search_runbook -> platform.enable_request_coalescing -> platform.warm_cache |
| 151 | `sim_gen_cache_warm_search_index_019` | Cache outage on search_index during 0.5x peak | 0.6 | 14 | platform.read_slack -> platform.get_traffic -> platform.get_logs -> platform.search_runbook -> platform.enable_request_coalescing -> platform.warm_cache |
| 152 | `sim_gen_cache_warm_search_index_022` | Cache outage on search_index during 0.5x peak | 0.6 | 14 | platform.read_slack -> platform.get_traffic -> platform.get_logs -> platform.search_runbook -> platform.enable_request_coalescing -> platform.warm_cache |
| 153 | `sim_gen_cache_warm_session_cache_001` | Cache outage on session_cache during 0.5x peak | 0.6 | 14 | platform.read_slack -> platform.get_traffic -> platform.get_logs -> platform.search_runbook -> platform.enable_request_coalescing -> platform.warm_cache |
| 154 | `sim_gen_cache_warm_session_cache_004` | Cache outage on session_cache during 0.5x peak | 0.6 | 14 | platform.read_slack -> platform.get_traffic -> platform.get_logs -> platform.search_runbook -> platform.enable_request_coalescing -> platform.warm_cache |
| 155 | `sim_gen_cache_warm_session_cache_007` | Cache outage on session_cache during 0.5x peak | 0.6 | 14 | platform.read_slack -> platform.get_traffic -> platform.get_logs -> platform.search_runbook -> platform.enable_request_coalescing -> platform.warm_cache |
| 156 | `sim_gen_cache_warm_session_cache_010` | Cache outage on session_cache during 0.5x peak | 0.6 | 14 | platform.read_slack -> platform.get_traffic -> platform.get_logs -> platform.search_runbook -> platform.enable_request_coalescing -> platform.warm_cache |

## Medium tier - 128 scenarios

| # | ID | Title | Target | Max steps | Correct chain |
|---:|---|---|---:|---:|---|
| 1 | `sim_gen_app_leak_api_gateway_041` | Memory leak in api_gateway (aggro=0.8) | 0.55 | 16 | platform.read_slack -> platform.get_logs -> platform.get_metrics -> platform.pause_health_checks -> platform.capture_memory_dump -> platform.rollback_deployment -> platform.resume_health_checks |
| 2 | `sim_gen_app_leak_api_gateway_042` | Memory leak in api_gateway (aggro=0.8) | 0.55 | 16 | platform.read_slack -> platform.get_logs -> platform.get_metrics -> platform.pause_health_checks -> platform.capture_memory_dump -> platform.rollback_deployment -> platform.resume_health_checks |
| 3 | `sim_gen_app_leak_auth_005` | Memory leak in auth (aggro=0.8) | 0.55 | 16 | platform.read_slack -> platform.get_logs -> platform.get_metrics -> platform.pause_health_checks -> platform.capture_memory_dump -> platform.rollback_deployment -> platform.resume_health_checks |
| 4 | `sim_gen_app_leak_auth_006` | Memory leak in auth (aggro=0.8) | 0.55 | 16 | platform.read_slack -> platform.get_logs -> platform.get_metrics -> platform.pause_health_checks -> platform.capture_memory_dump -> platform.rollback_deployment -> platform.resume_health_checks |
| 5 | `sim_gen_app_leak_catalog_017` | Memory leak in catalog (aggro=0.8) | 0.55 | 16 | platform.read_slack -> platform.get_logs -> platform.get_metrics -> platform.pause_health_checks -> platform.capture_memory_dump -> platform.rollback_deployment -> platform.resume_health_checks |
| 6 | `sim_gen_app_leak_catalog_018` | Memory leak in catalog (aggro=0.8) | 0.55 | 16 | platform.read_slack -> platform.get_logs -> platform.get_metrics -> platform.pause_health_checks -> platform.capture_memory_dump -> platform.rollback_deployment -> platform.resume_health_checks |
| 7 | `sim_gen_app_leak_checkout_011` | Memory leak in checkout (aggro=0.8) | 0.55 | 16 | platform.read_slack -> platform.get_logs -> platform.get_metrics -> platform.pause_health_checks -> platform.capture_memory_dump -> platform.rollback_deployment -> platform.resume_health_checks |
| 8 | `sim_gen_app_leak_checkout_012` | Memory leak in checkout (aggro=0.8) | 0.55 | 16 | platform.read_slack -> platform.get_logs -> platform.get_metrics -> platform.pause_health_checks -> platform.capture_memory_dump -> platform.rollback_deployment -> platform.resume_health_checks |
| 9 | `sim_gen_app_leak_frontend_035` | Memory leak in frontend (aggro=0.8) | 0.55 | 16 | platform.read_slack -> platform.get_logs -> platform.get_metrics -> platform.pause_health_checks -> platform.capture_memory_dump -> platform.rollback_deployment -> platform.resume_health_checks |
| 10 | `sim_gen_app_leak_frontend_036` | Memory leak in frontend (aggro=0.8) | 0.55 | 16 | platform.read_slack -> platform.get_logs -> platform.get_metrics -> platform.pause_health_checks -> platform.capture_memory_dump -> platform.rollback_deployment -> platform.resume_health_checks |
| 11 | `sim_gen_app_leak_inventory_029` | Memory leak in inventory (aggro=0.8) | 0.55 | 16 | platform.read_slack -> platform.get_logs -> platform.get_metrics -> platform.pause_health_checks -> platform.capture_memory_dump -> platform.rollback_deployment -> platform.resume_health_checks |
| 12 | `sim_gen_app_leak_inventory_030` | Memory leak in inventory (aggro=0.8) | 0.55 | 16 | platform.read_slack -> platform.get_logs -> platform.get_metrics -> platform.pause_health_checks -> platform.capture_memory_dump -> platform.rollback_deployment -> platform.resume_health_checks |
| 13 | `sim_gen_app_leak_payments_023` | Memory leak in payments (aggro=0.8) | 0.55 | 16 | platform.read_slack -> platform.get_logs -> platform.get_metrics -> platform.pause_health_checks -> platform.capture_memory_dump -> platform.rollback_deployment -> platform.resume_health_checks |
| 14 | `sim_gen_app_leak_payments_024` | Memory leak in payments (aggro=0.8) | 0.55 | 16 | platform.read_slack -> platform.get_logs -> platform.get_metrics -> platform.pause_health_checks -> platform.capture_memory_dump -> platform.rollback_deployment -> platform.resume_health_checks |
| 15 | `sim_gen_cache_warm_search_index_014` | Cache outage on search_index during 1.0x peak | 0.6 | 14 | platform.read_slack -> platform.get_traffic -> platform.get_logs -> platform.search_runbook -> platform.enable_request_coalescing -> platform.warm_cache |
| 16 | `sim_gen_cache_warm_search_index_015` | Cache outage on search_index during 1.4x peak | 0.6 | 14 | platform.read_slack -> platform.get_traffic -> platform.get_logs -> platform.search_runbook -> platform.enable_request_coalescing -> platform.warm_cache |
| 17 | `sim_gen_cache_warm_search_index_017` | Cache outage on search_index during 1.0x peak | 0.6 | 14 | platform.read_slack -> platform.get_traffic -> platform.get_logs -> platform.search_runbook -> platform.enable_request_coalescing -> platform.warm_cache |
| 18 | `sim_gen_cache_warm_search_index_018` | Cache outage on search_index during 1.4x peak | 0.6 | 14 | platform.read_slack -> platform.get_traffic -> platform.get_logs -> platform.search_runbook -> platform.enable_request_coalescing -> platform.warm_cache |
| 19 | `sim_gen_cache_warm_search_index_020` | Cache outage on search_index during 1.0x peak | 0.6 | 14 | platform.read_slack -> platform.get_traffic -> platform.get_logs -> platform.search_runbook -> platform.enable_request_coalescing -> platform.warm_cache |
| 20 | `sim_gen_cache_warm_search_index_021` | Cache outage on search_index during 1.4x peak | 0.6 | 14 | platform.read_slack -> platform.get_traffic -> platform.get_logs -> platform.search_runbook -> platform.enable_request_coalescing -> platform.warm_cache |
| 21 | `sim_gen_cache_warm_search_index_023` | Cache outage on search_index during 1.0x peak | 0.6 | 14 | platform.read_slack -> platform.get_traffic -> platform.get_logs -> platform.search_runbook -> platform.enable_request_coalescing -> platform.warm_cache |
| 22 | `sim_gen_cache_warm_search_index_024` | Cache outage on search_index during 1.4x peak | 0.6 | 14 | platform.read_slack -> platform.get_traffic -> platform.get_logs -> platform.search_runbook -> platform.enable_request_coalescing -> platform.warm_cache |
| 23 | `sim_gen_cache_warm_session_cache_002` | Cache outage on session_cache during 1.0x peak | 0.6 | 14 | platform.read_slack -> platform.get_traffic -> platform.get_logs -> platform.search_runbook -> platform.enable_request_coalescing -> platform.warm_cache |
| 24 | `sim_gen_cache_warm_session_cache_003` | Cache outage on session_cache during 1.4x peak | 0.6 | 14 | platform.read_slack -> platform.get_traffic -> platform.get_logs -> platform.search_runbook -> platform.enable_request_coalescing -> platform.warm_cache |
| 25 | `sim_gen_cache_warm_session_cache_005` | Cache outage on session_cache during 1.0x peak | 0.6 | 14 | platform.read_slack -> platform.get_traffic -> platform.get_logs -> platform.search_runbook -> platform.enable_request_coalescing -> platform.warm_cache |
| 26 | `sim_gen_cache_warm_session_cache_006` | Cache outage on session_cache during 1.4x peak | 0.6 | 14 | platform.read_slack -> platform.get_traffic -> platform.get_logs -> platform.search_runbook -> platform.enable_request_coalescing -> platform.warm_cache |
| 27 | `sim_gen_cache_warm_session_cache_008` | Cache outage on session_cache during 1.0x peak | 0.6 | 14 | platform.read_slack -> platform.get_traffic -> platform.get_logs -> platform.search_runbook -> platform.enable_request_coalescing -> platform.warm_cache |
| 28 | `sim_gen_cache_warm_session_cache_009` | Cache outage on session_cache during 1.4x peak | 0.6 | 14 | platform.read_slack -> platform.get_traffic -> platform.get_logs -> platform.search_runbook -> platform.enable_request_coalescing -> platform.warm_cache |
| 29 | `sim_gen_cache_warm_session_cache_011` | Cache outage on session_cache during 1.0x peak | 0.6 | 14 | platform.read_slack -> platform.get_traffic -> platform.get_logs -> platform.search_runbook -> platform.enable_request_coalescing -> platform.warm_cache |
| 30 | `sim_gen_cache_warm_session_cache_012` | Cache outage on session_cache during 1.4x peak | 0.6 | 14 | platform.read_slack -> platform.get_traffic -> platform.get_logs -> platform.search_runbook -> platform.enable_request_coalescing -> platform.warm_cache |
| 31 | `sim_gen_peak_api_gateway_004` | Sine-wave peak hammers api_gateway (x1.2) | 0.55 | 14 | platform.read_slack -> platform.get_traffic -> platform.get_metrics -> platform.enable_request_coalescing -> platform.warm_cache |
| 32 | `sim_gen_peak_api_gateway_005` | Sine-wave peak hammers api_gateway (x1.5) | 0.55 | 14 | platform.read_slack -> platform.get_traffic -> platform.get_metrics -> platform.enable_request_coalescing -> platform.warm_cache |
| 33 | `sim_gen_peak_api_gateway_006` | Sine-wave peak hammers api_gateway (x1.8) | 0.55 | 14 | platform.read_slack -> platform.get_traffic -> platform.get_metrics -> platform.enable_request_coalescing -> platform.warm_cache |
| 34 | `sim_gen_peak_auth_010` | Sine-wave peak hammers auth (x1.2) | 0.55 | 14 | platform.read_slack -> platform.get_traffic -> platform.get_metrics -> platform.enable_request_coalescing -> platform.warm_cache |
| 35 | `sim_gen_peak_auth_011` | Sine-wave peak hammers auth (x1.5) | 0.55 | 14 | platform.read_slack -> platform.get_traffic -> platform.get_metrics -> platform.enable_request_coalescing -> platform.warm_cache |
| 36 | `sim_gen_peak_auth_012` | Sine-wave peak hammers auth (x1.8) | 0.55 | 14 | platform.read_slack -> platform.get_traffic -> platform.get_metrics -> platform.enable_request_coalescing -> platform.warm_cache |
| 37 | `sim_gen_peak_catalog_016` | Sine-wave peak hammers catalog (x1.2) | 0.55 | 14 | platform.read_slack -> platform.get_traffic -> platform.get_metrics -> platform.enable_request_coalescing -> platform.warm_cache |
| 38 | `sim_gen_peak_catalog_017` | Sine-wave peak hammers catalog (x1.5) | 0.55 | 14 | platform.read_slack -> platform.get_traffic -> platform.get_metrics -> platform.enable_request_coalescing -> platform.warm_cache |
| 39 | `sim_gen_peak_catalog_018` | Sine-wave peak hammers catalog (x1.8) | 0.55 | 14 | platform.read_slack -> platform.get_traffic -> platform.get_metrics -> platform.enable_request_coalescing -> platform.warm_cache |
| 40 | `sim_gen_peak_cdn_007` | Sine-wave peak hammers cdn (x1.2) | 0.55 | 14 | platform.read_slack -> platform.get_traffic -> platform.get_metrics -> platform.enable_request_coalescing -> platform.warm_cache |
| 41 | `sim_gen_peak_cdn_008` | Sine-wave peak hammers cdn (x1.5) | 0.55 | 14 | platform.read_slack -> platform.get_traffic -> platform.get_metrics -> platform.enable_request_coalescing -> platform.warm_cache |
| 42 | `sim_gen_peak_cdn_009` | Sine-wave peak hammers cdn (x1.8) | 0.55 | 14 | platform.read_slack -> platform.get_traffic -> platform.get_metrics -> platform.enable_request_coalescing -> platform.warm_cache |
| 43 | `sim_gen_peak_checkout_013` | Sine-wave peak hammers checkout (x1.2) | 0.55 | 14 | platform.read_slack -> platform.get_traffic -> platform.get_metrics -> platform.enable_request_coalescing -> platform.warm_cache |
| 44 | `sim_gen_peak_checkout_014` | Sine-wave peak hammers checkout (x1.5) | 0.55 | 14 | platform.read_slack -> platform.get_traffic -> platform.get_metrics -> platform.enable_request_coalescing -> platform.warm_cache |
| 45 | `sim_gen_peak_checkout_015` | Sine-wave peak hammers checkout (x1.8) | 0.55 | 14 | platform.read_slack -> platform.get_traffic -> platform.get_metrics -> platform.enable_request_coalescing -> platform.warm_cache |
| 46 | `sim_gen_peak_frontend_001` | Sine-wave peak hammers frontend (x1.2) | 0.55 | 14 | platform.read_slack -> platform.get_traffic -> platform.get_metrics -> platform.enable_request_coalescing -> platform.warm_cache |
| 47 | `sim_gen_peak_frontend_002` | Sine-wave peak hammers frontend (x1.5) | 0.55 | 14 | platform.read_slack -> platform.get_traffic -> platform.get_metrics -> platform.enable_request_coalescing -> platform.warm_cache |
| 48 | `sim_gen_peak_frontend_003` | Sine-wave peak hammers frontend (x1.8) | 0.55 | 14 | platform.read_slack -> platform.get_traffic -> platform.get_metrics -> platform.enable_request_coalescing -> platform.warm_cache |
| 49 | `sim_gen_redherring_auth_001` | Red-herring on Slack — true cause is leak in auth | 0.6 | 16 | platform.read_slack -> platform.get_logs -> platform.get_metrics -> platform.pause_health_checks -> platform.capture_memory_dump -> platform.rollback_deployment -> platform.resume_health_checks |
| 50 | `sim_gen_redherring_auth_002` | Red-herring on Slack — true cause is leak in auth | 0.6 | 16 | platform.read_slack -> platform.get_logs -> platform.get_metrics -> platform.pause_health_checks -> platform.capture_memory_dump -> platform.rollback_deployment -> platform.resume_health_checks |
| 51 | `sim_gen_redherring_auth_003` | Red-herring on Slack — true cause is leak in auth | 0.6 | 16 | platform.read_slack -> platform.get_logs -> platform.get_metrics -> platform.pause_health_checks -> platform.capture_memory_dump -> platform.rollback_deployment -> platform.resume_health_checks |
| 52 | `sim_gen_redherring_auth_004` | Red-herring on Slack — true cause is leak in auth | 0.6 | 16 | platform.read_slack -> platform.get_logs -> platform.get_metrics -> platform.pause_health_checks -> platform.capture_memory_dump -> platform.rollback_deployment -> platform.resume_health_checks |
| 53 | `sim_gen_redherring_catalog_009` | Red-herring on Slack — true cause is leak in catalog | 0.6 | 16 | platform.read_slack -> platform.get_logs -> platform.get_metrics -> platform.pause_health_checks -> platform.capture_memory_dump -> platform.rollback_deployment -> platform.resume_health_checks |
| 54 | `sim_gen_redherring_catalog_010` | Red-herring on Slack — true cause is leak in catalog | 0.6 | 16 | platform.read_slack -> platform.get_logs -> platform.get_metrics -> platform.pause_health_checks -> platform.capture_memory_dump -> platform.rollback_deployment -> platform.resume_health_checks |
| 55 | `sim_gen_redherring_catalog_011` | Red-herring on Slack — true cause is leak in catalog | 0.6 | 16 | platform.read_slack -> platform.get_logs -> platform.get_metrics -> platform.pause_health_checks -> platform.capture_memory_dump -> platform.rollback_deployment -> platform.resume_health_checks |
| 56 | `sim_gen_redherring_catalog_012` | Red-herring on Slack — true cause is leak in catalog | 0.6 | 16 | platform.read_slack -> platform.get_logs -> platform.get_metrics -> platform.pause_health_checks -> platform.capture_memory_dump -> platform.rollback_deployment -> platform.resume_health_checks |
| 57 | `sim_gen_redherring_checkout_005` | Red-herring on Slack — true cause is leak in checkout | 0.6 | 16 | platform.read_slack -> platform.get_logs -> platform.get_metrics -> platform.pause_health_checks -> platform.capture_memory_dump -> platform.rollback_deployment -> platform.resume_health_checks |
| 58 | `sim_gen_redherring_checkout_006` | Red-herring on Slack — true cause is leak in checkout | 0.6 | 16 | platform.read_slack -> platform.get_logs -> platform.get_metrics -> platform.pause_health_checks -> platform.capture_memory_dump -> platform.rollback_deployment -> platform.resume_health_checks |
| 59 | `sim_gen_redherring_checkout_007` | Red-herring on Slack — true cause is leak in checkout | 0.6 | 16 | platform.read_slack -> platform.get_logs -> platform.get_metrics -> platform.pause_health_checks -> platform.capture_memory_dump -> platform.rollback_deployment -> platform.resume_health_checks |
| 60 | `sim_gen_redherring_checkout_008` | Red-herring on Slack — true cause is leak in checkout | 0.6 | 16 | platform.read_slack -> platform.get_logs -> platform.get_metrics -> platform.pause_health_checks -> platform.capture_memory_dump -> platform.rollback_deployment -> platform.resume_health_checks |
| 61 | `sim_gen_redherring_inventory_017` | Red-herring on Slack — true cause is leak in inventory | 0.6 | 16 | platform.read_slack -> platform.get_logs -> platform.get_metrics -> platform.pause_health_checks -> platform.capture_memory_dump -> platform.rollback_deployment -> platform.resume_health_checks |
| 62 | `sim_gen_redherring_inventory_018` | Red-herring on Slack — true cause is leak in inventory | 0.6 | 16 | platform.read_slack -> platform.get_logs -> platform.get_metrics -> platform.pause_health_checks -> platform.capture_memory_dump -> platform.rollback_deployment -> platform.resume_health_checks |
| 63 | `sim_gen_redherring_inventory_019` | Red-herring on Slack — true cause is leak in inventory | 0.6 | 16 | platform.read_slack -> platform.get_logs -> platform.get_metrics -> platform.pause_health_checks -> platform.capture_memory_dump -> platform.rollback_deployment -> platform.resume_health_checks |
| 64 | `sim_gen_redherring_inventory_020` | Red-herring on Slack — true cause is leak in inventory | 0.6 | 16 | platform.read_slack -> platform.get_logs -> platform.get_metrics -> platform.pause_health_checks -> platform.capture_memory_dump -> platform.rollback_deployment -> platform.resume_health_checks |
| 65 | `sim_gen_redherring_payments_013` | Red-herring on Slack — true cause is leak in payments | 0.6 | 16 | platform.read_slack -> platform.get_logs -> platform.get_metrics -> platform.pause_health_checks -> platform.capture_memory_dump -> platform.rollback_deployment -> platform.resume_health_checks |
| 66 | `sim_gen_redherring_payments_014` | Red-herring on Slack — true cause is leak in payments | 0.6 | 16 | platform.read_slack -> platform.get_logs -> platform.get_metrics -> platform.pause_health_checks -> platform.capture_memory_dump -> platform.rollback_deployment -> platform.resume_health_checks |
| 67 | `sim_gen_redherring_payments_015` | Red-herring on Slack — true cause is leak in payments | 0.6 | 16 | platform.read_slack -> platform.get_logs -> platform.get_metrics -> platform.pause_health_checks -> platform.capture_memory_dump -> platform.rollback_deployment -> platform.resume_health_checks |
| 68 | `sim_gen_redherring_payments_016` | Red-herring on Slack — true cause is leak in payments | 0.6 | 16 | platform.read_slack -> platform.get_logs -> platform.get_metrics -> platform.pause_health_checks -> platform.capture_memory_dump -> platform.rollback_deployment -> platform.resume_health_checks |
| 69 | `sim_med_eb_lambda_016` | checkout pipeline silent | 0.55 | 16 | events.describe -> events.enable -> events.publish |
| 70 | `sim_med_eb_lambda_017` | orders pipeline silent | 0.55 | 16 | events.describe -> events.enable -> events.publish |
| 71 | `sim_med_eb_lambda_018` | inventory pipeline silent | 0.55 | 16 | events.describe -> events.enable -> events.publish |
| 72 | `sim_med_eb_lambda_019` | payments pipeline silent | 0.55 | 16 | events.describe -> events.enable -> events.publish |
| 73 | `sim_med_eb_lambda_020` | search pipeline silent | 0.55 | 16 | events.describe -> events.enable -> events.publish |
| 74 | `sim_med_eb_lambda_021` | recommendations pipeline silent | 0.55 | 16 | events.describe -> events.enable -> events.publish |
| 75 | `sim_med_eb_lambda_022` | auth pipeline silent | 0.55 | 16 | events.describe -> events.enable -> events.publish |
| 76 | `sim_med_eb_lambda_023` | billing pipeline silent | 0.55 | 16 | events.describe -> events.enable -> events.publish |
| 77 | `sim_med_eb_lambda_024` | shipping pipeline silent | 0.55 | 16 | events.describe -> events.enable -> events.publish |
| 78 | `sim_med_eb_lambda_025` | notifications pipeline silent | 0.55 | 16 | events.describe -> events.enable -> events.publish |
| 79 | `sim_med_eb_lambda_026` | reviews pipeline silent | 0.55 | 16 | events.describe -> events.enable -> events.publish |
| 80 | `sim_med_eb_lambda_027` | catalog pipeline silent | 0.55 | 16 | events.describe -> events.enable -> events.publish |
| 81 | `sim_med_eb_lambda_028` | fulfillment pipeline silent | 0.55 | 16 | events.describe -> events.enable -> events.publish |
| 82 | `sim_med_eb_lambda_029` | telemetry pipeline silent | 0.55 | 16 | events.describe -> events.enable -> events.publish |
| 83 | `sim_med_eb_lambda_030` | analytics pipeline silent | 0.55 | 16 | events.describe -> events.enable -> events.publish |
| 84 | `sim_med_kms_lambda_031` | checkout Lambda 5xx after KMS change | 0.6 | 18 | lambda.describe -> lambda.invoke -> kms.describe -> kms.enable -> lambda.invoke |
| 85 | `sim_med_kms_lambda_032` | orders Lambda 5xx after KMS change | 0.6 | 18 | lambda.describe -> lambda.invoke -> kms.describe -> kms.enable -> lambda.invoke |
| 86 | `sim_med_kms_lambda_033` | inventory Lambda 5xx after KMS change | 0.6 | 18 | lambda.describe -> lambda.invoke -> kms.describe -> kms.enable -> lambda.invoke |
| 87 | `sim_med_kms_lambda_034` | payments Lambda 5xx after KMS change | 0.6 | 18 | lambda.describe -> lambda.invoke -> kms.describe -> kms.enable -> lambda.invoke |
| 88 | `sim_med_kms_lambda_035` | search Lambda 5xx after KMS change | 0.6 | 18 | lambda.describe -> lambda.invoke -> kms.describe -> kms.enable -> lambda.invoke |
| 89 | `sim_med_kms_lambda_036` | recommendations Lambda 5xx after KMS change | 0.6 | 18 | lambda.describe -> lambda.invoke -> kms.describe -> kms.enable -> lambda.invoke |
| 90 | `sim_med_kms_lambda_037` | auth Lambda 5xx after KMS change | 0.6 | 18 | lambda.describe -> lambda.invoke -> kms.describe -> kms.enable -> lambda.invoke |
| 91 | `sim_med_kms_lambda_038` | billing Lambda 5xx after KMS change | 0.6 | 18 | lambda.describe -> lambda.invoke -> kms.describe -> kms.enable -> lambda.invoke |
| 92 | `sim_med_kms_lambda_039` | shipping Lambda 5xx after KMS change | 0.6 | 18 | lambda.describe -> lambda.invoke -> kms.describe -> kms.enable -> lambda.invoke |
| 93 | `sim_med_kms_lambda_040` | notifications Lambda 5xx after KMS change | 0.6 | 18 | lambda.describe -> lambda.invoke -> kms.describe -> kms.enable -> lambda.invoke |
| 94 | `sim_med_kms_lambda_041` | reviews Lambda 5xx after KMS change | 0.6 | 18 | lambda.describe -> lambda.invoke -> kms.describe -> kms.enable -> lambda.invoke |
| 95 | `sim_med_kms_lambda_042` | catalog Lambda 5xx after KMS change | 0.6 | 18 | lambda.describe -> lambda.invoke -> kms.describe -> kms.enable -> lambda.invoke |
| 96 | `sim_med_kms_lambda_043` | fulfillment Lambda 5xx after KMS change | 0.6 | 18 | lambda.describe -> lambda.invoke -> kms.describe -> kms.enable -> lambda.invoke |
| 97 | `sim_med_kms_lambda_044` | telemetry Lambda 5xx after KMS change | 0.6 | 18 | lambda.describe -> lambda.invoke -> kms.describe -> kms.enable -> lambda.invoke |
| 98 | `sim_med_kms_lambda_045` | analytics Lambda 5xx after KMS change | 0.6 | 18 | lambda.describe -> lambda.invoke -> kms.describe -> kms.enable -> lambda.invoke |
| 99 | `sim_med_lambda_secret_001` | checkout Lambda errors spike | 0.6 | 18 | lambda.describe -> lambda.invoke -> secretsmanager.describe -> secretsmanager.rotate -> lambda.invoke |
| 100 | `sim_med_lambda_secret_002` | orders Lambda errors spike | 0.6 | 18 | lambda.describe -> lambda.invoke -> secretsmanager.describe -> secretsmanager.rotate -> lambda.invoke |
| 101 | `sim_med_lambda_secret_003` | inventory Lambda errors spike | 0.6 | 18 | lambda.describe -> lambda.invoke -> secretsmanager.describe -> secretsmanager.rotate -> lambda.invoke |
| 102 | `sim_med_lambda_secret_004` | payments Lambda errors spike | 0.6 | 18 | lambda.describe -> lambda.invoke -> secretsmanager.describe -> secretsmanager.rotate -> lambda.invoke |
| 103 | `sim_med_lambda_secret_005` | search Lambda errors spike | 0.6 | 18 | lambda.describe -> lambda.invoke -> secretsmanager.describe -> secretsmanager.rotate -> lambda.invoke |
| 104 | `sim_med_lambda_secret_006` | recommendations Lambda errors spike | 0.6 | 18 | lambda.describe -> lambda.invoke -> secretsmanager.describe -> secretsmanager.rotate -> lambda.invoke |
| 105 | `sim_med_lambda_secret_007` | auth Lambda errors spike | 0.6 | 18 | lambda.describe -> lambda.invoke -> secretsmanager.describe -> secretsmanager.rotate -> lambda.invoke |
| 106 | `sim_med_lambda_secret_008` | billing Lambda errors spike | 0.6 | 18 | lambda.describe -> lambda.invoke -> secretsmanager.describe -> secretsmanager.rotate -> lambda.invoke |
| 107 | `sim_med_lambda_secret_009` | shipping Lambda errors spike | 0.6 | 18 | lambda.describe -> lambda.invoke -> secretsmanager.describe -> secretsmanager.rotate -> lambda.invoke |
| 108 | `sim_med_lambda_secret_010` | notifications Lambda errors spike | 0.6 | 18 | lambda.describe -> lambda.invoke -> secretsmanager.describe -> secretsmanager.rotate -> lambda.invoke |
| 109 | `sim_med_lambda_secret_011` | reviews Lambda errors spike | 0.6 | 18 | lambda.describe -> lambda.invoke -> secretsmanager.describe -> secretsmanager.rotate -> lambda.invoke |
| 110 | `sim_med_lambda_secret_012` | catalog Lambda errors spike | 0.6 | 18 | lambda.describe -> lambda.invoke -> secretsmanager.describe -> secretsmanager.rotate -> lambda.invoke |
| 111 | `sim_med_lambda_secret_013` | fulfillment Lambda errors spike | 0.6 | 18 | lambda.describe -> lambda.invoke -> secretsmanager.describe -> secretsmanager.rotate -> lambda.invoke |
| 112 | `sim_med_lambda_secret_014` | telemetry Lambda errors spike | 0.6 | 18 | lambda.describe -> lambda.invoke -> secretsmanager.describe -> secretsmanager.rotate -> lambda.invoke |
| 113 | `sim_med_lambda_secret_015` | analytics Lambda errors spike | 0.6 | 18 | lambda.describe -> lambda.invoke -> secretsmanager.describe -> secretsmanager.rotate -> lambda.invoke |
| 114 | `sim_med_sfn_lambda_046` | checkout state machine failing | 0.55 | 18 | stepfunctions.describe -> lambda.describe -> lambda.scale -> stepfunctions.start |
| 115 | `sim_med_sfn_lambda_047` | orders state machine failing | 0.55 | 18 | stepfunctions.describe -> lambda.describe -> lambda.scale -> stepfunctions.start |
| 116 | `sim_med_sfn_lambda_048` | inventory state machine failing | 0.55 | 18 | stepfunctions.describe -> lambda.describe -> lambda.scale -> stepfunctions.start |
| 117 | `sim_med_sfn_lambda_049` | payments state machine failing | 0.55 | 18 | stepfunctions.describe -> lambda.describe -> lambda.scale -> stepfunctions.start |
| 118 | `sim_med_sfn_lambda_050` | search state machine failing | 0.55 | 18 | stepfunctions.describe -> lambda.describe -> lambda.scale -> stepfunctions.start |
| 119 | `sim_med_sfn_lambda_051` | recommendations state machine failing | 0.55 | 18 | stepfunctions.describe -> lambda.describe -> lambda.scale -> stepfunctions.start |
| 120 | `sim_med_sfn_lambda_052` | auth state machine failing | 0.55 | 18 | stepfunctions.describe -> lambda.describe -> lambda.scale -> stepfunctions.start |
| 121 | `sim_med_sfn_lambda_053` | billing state machine failing | 0.55 | 18 | stepfunctions.describe -> lambda.describe -> lambda.scale -> stepfunctions.start |
| 122 | `sim_med_sfn_lambda_054` | shipping state machine failing | 0.55 | 18 | stepfunctions.describe -> lambda.describe -> lambda.scale -> stepfunctions.start |
| 123 | `sim_med_sfn_lambda_055` | notifications state machine failing | 0.55 | 18 | stepfunctions.describe -> lambda.describe -> lambda.scale -> stepfunctions.start |
| 124 | `sim_med_sfn_lambda_056` | reviews state machine failing | 0.55 | 18 | stepfunctions.describe -> lambda.describe -> lambda.scale -> stepfunctions.start |
| 125 | `sim_med_sfn_lambda_057` | catalog state machine failing | 0.55 | 18 | stepfunctions.describe -> lambda.describe -> lambda.scale -> stepfunctions.start |
| 126 | `sim_med_sfn_lambda_058` | fulfillment state machine failing | 0.55 | 18 | stepfunctions.describe -> lambda.describe -> lambda.scale -> stepfunctions.start |
| 127 | `sim_med_sfn_lambda_059` | telemetry state machine failing | 0.55 | 18 | stepfunctions.describe -> lambda.describe -> lambda.scale -> stepfunctions.start |
| 128 | `sim_med_sfn_lambda_060` | analytics state machine failing | 0.55 | 18 | stepfunctions.describe -> lambda.describe -> lambda.scale -> stepfunctions.start |

## Hard tier - 97 scenarios

| # | ID | Title | Target | Max steps | Correct chain |
|---:|---|---|---:|---:|---|
| 1 | `sim_advanced_cascade_users_db_001` | Cascade: users_db memory-leak hides behind frontend 504s | 0.55 | 20 | platform.get_logs -> platform.get_trace -> platform.get_metrics -> platform.search_runbook -> platform.pause_health_checks -> platform.capture_memory_dump -> platform.failover_replica |
| 2 | `sim_advanced_runbook_trap_postgres_001` | Trap: TXID wraparound — restart corrupts the DB | 0.55 | 20 | platform.get_logs -> platform.search_runbook -> platform.read_runbook -> platform.vacuum_freeze_db |
| 3 | `sim_advanced_saboteur_duel_001` | 1v1 Duel — Active Saboteur attacks auth_db, then choke-holds the replica | 0.65 | 20 | platform.read_slack -> platform.get_logs -> platform.get_trace -> platform.failover_replica -> platform.read_slack -> platform.get_metrics -> platform.rollback_deployment |
| 4 | `sim_advanced_slack_redherring_001` | Slack Red-Herring — A frontend dev claims their hotfix broke checkout | 0.6 | 16 | platform.read_slack -> platform.get_logs -> platform.get_metrics -> platform.pause_health_checks -> platform.capture_memory_dump -> platform.rollback_deployment -> platform.resume_health_checks |
| 5 | `sim_advanced_trolley_orders_db_001` | Trolley: orders_db index corrupted — rebuild vs restore | 0.55 | 20 | platform.get_logs -> platform.get_trace -> platform.search_runbook -> platform.restore_from_backup |
| 6 | `sim_gen_cascade_catalog_db_013` | Dependency cascade — catalog_db is degraded, surfacing as alerts on api_gateway | 0.65 | 18 | platform.read_slack -> platform.describe_topology -> platform.get_logs -> platform.get_logs -> platform.get_trace -> platform.vacuum_freeze_db |
| 7 | `sim_gen_cascade_catalog_db_014` | Dependency cascade — catalog_db is degraded, surfacing as alerts on api_gateway | 0.65 | 18 | platform.read_slack -> platform.describe_topology -> platform.get_logs -> platform.get_logs -> platform.get_trace -> platform.vacuum_freeze_db |
| 8 | `sim_gen_cascade_catalog_db_015` | Dependency cascade — catalog_db is memory_leak, surfacing as alerts on api_gateway | 0.65 | 18 | platform.read_slack -> platform.describe_topology -> platform.get_logs -> platform.get_logs -> platform.get_trace -> platform.vacuum_freeze_db |
| 9 | `sim_gen_cascade_catalog_db_016` | Dependency cascade — catalog_db is memory_leak, surfacing as alerts on api_gateway | 0.65 | 18 | platform.read_slack -> platform.describe_topology -> platform.get_logs -> platform.get_logs -> platform.get_trace -> platform.vacuum_freeze_db |
| 10 | `sim_gen_cascade_catalog_db_017` | Dependency cascade — catalog_db is cpu_throttled, surfacing as alerts on api_gateway | 0.65 | 18 | platform.read_slack -> platform.describe_topology -> platform.get_logs -> platform.get_logs -> platform.get_trace -> platform.vacuum_freeze_db |
| 11 | `sim_gen_cascade_catalog_db_018` | Dependency cascade — catalog_db is cpu_throttled, surfacing as alerts on api_gateway | 0.65 | 18 | platform.read_slack -> platform.describe_topology -> platform.get_logs -> platform.get_logs -> platform.get_trace -> platform.vacuum_freeze_db |
| 12 | `sim_gen_cascade_inventory_db_007` | Dependency cascade — inventory_db is degraded, surfacing as alerts on checkout | 0.65 | 18 | platform.read_slack -> platform.describe_topology -> platform.get_logs -> platform.get_logs -> platform.get_trace -> platform.vacuum_freeze_db |
| 13 | `sim_gen_cascade_inventory_db_008` | Dependency cascade — inventory_db is degraded, surfacing as alerts on checkout | 0.65 | 18 | platform.read_slack -> platform.describe_topology -> platform.get_logs -> platform.get_logs -> platform.get_trace -> platform.vacuum_freeze_db |
| 14 | `sim_gen_cascade_inventory_db_009` | Dependency cascade — inventory_db is memory_leak, surfacing as alerts on checkout | 0.65 | 18 | platform.read_slack -> platform.describe_topology -> platform.get_logs -> platform.get_logs -> platform.get_trace -> platform.vacuum_freeze_db |
| 15 | `sim_gen_cascade_inventory_db_010` | Dependency cascade — inventory_db is memory_leak, surfacing as alerts on checkout | 0.65 | 18 | platform.read_slack -> platform.describe_topology -> platform.get_logs -> platform.get_logs -> platform.get_trace -> platform.vacuum_freeze_db |
| 16 | `sim_gen_cascade_inventory_db_011` | Dependency cascade — inventory_db is cpu_throttled, surfacing as alerts on checkout | 0.65 | 18 | platform.read_slack -> platform.describe_topology -> platform.get_logs -> platform.get_logs -> platform.get_trace -> platform.vacuum_freeze_db |
| 17 | `sim_gen_cascade_inventory_db_012` | Dependency cascade — inventory_db is cpu_throttled, surfacing as alerts on checkout | 0.65 | 18 | platform.read_slack -> platform.describe_topology -> platform.get_logs -> platform.get_logs -> platform.get_trace -> platform.vacuum_freeze_db |
| 18 | `sim_gen_cascade_orders_db_025` | Dependency cascade — orders_db is degraded, surfacing as alerts on api_gateway | 0.65 | 18 | platform.read_slack -> platform.describe_topology -> platform.get_logs -> platform.get_logs -> platform.get_trace -> platform.vacuum_freeze_db |
| 19 | `sim_gen_cascade_orders_db_026` | Dependency cascade — orders_db is degraded, surfacing as alerts on api_gateway | 0.65 | 18 | platform.read_slack -> platform.describe_topology -> platform.get_logs -> platform.get_logs -> platform.get_trace -> platform.vacuum_freeze_db |
| 20 | `sim_gen_cascade_orders_db_027` | Dependency cascade — orders_db is memory_leak, surfacing as alerts on api_gateway | 0.65 | 18 | platform.read_slack -> platform.describe_topology -> platform.get_logs -> platform.get_logs -> platform.get_trace -> platform.vacuum_freeze_db |
| 21 | `sim_gen_cascade_orders_db_028` | Dependency cascade — orders_db is memory_leak, surfacing as alerts on api_gateway | 0.65 | 18 | platform.read_slack -> platform.describe_topology -> platform.get_logs -> platform.get_logs -> platform.get_trace -> platform.vacuum_freeze_db |
| 22 | `sim_gen_cascade_orders_db_029` | Dependency cascade — orders_db is cpu_throttled, surfacing as alerts on api_gateway | 0.65 | 18 | platform.read_slack -> platform.describe_topology -> platform.get_logs -> platform.get_logs -> platform.get_trace -> platform.vacuum_freeze_db |
| 23 | `sim_gen_cascade_orders_db_030` | Dependency cascade — orders_db is cpu_throttled, surfacing as alerts on api_gateway | 0.65 | 18 | platform.read_slack -> platform.describe_topology -> platform.get_logs -> platform.get_logs -> platform.get_trace -> platform.vacuum_freeze_db |
| 24 | `sim_gen_cascade_payments_db_001` | Dependency cascade — payments_db is degraded, surfacing as alerts on checkout | 0.65 | 18 | platform.read_slack -> platform.describe_topology -> platform.get_logs -> platform.get_logs -> platform.get_trace -> platform.vacuum_freeze_db |
| 25 | `sim_gen_cascade_payments_db_002` | Dependency cascade — payments_db is degraded, surfacing as alerts on checkout | 0.65 | 18 | platform.read_slack -> platform.describe_topology -> platform.get_logs -> platform.get_logs -> platform.get_trace -> platform.vacuum_freeze_db |
| 26 | `sim_gen_cascade_payments_db_003` | Dependency cascade — payments_db is memory_leak, surfacing as alerts on checkout | 0.65 | 18 | platform.read_slack -> platform.describe_topology -> platform.get_logs -> platform.get_logs -> platform.get_trace -> platform.vacuum_freeze_db |
| 27 | `sim_gen_cascade_payments_db_004` | Dependency cascade — payments_db is memory_leak, surfacing as alerts on checkout | 0.65 | 18 | platform.read_slack -> platform.describe_topology -> platform.get_logs -> platform.get_logs -> platform.get_trace -> platform.vacuum_freeze_db |
| 28 | `sim_gen_cascade_payments_db_005` | Dependency cascade — payments_db is cpu_throttled, surfacing as alerts on checkout | 0.65 | 18 | platform.read_slack -> platform.describe_topology -> platform.get_logs -> platform.get_logs -> platform.get_trace -> platform.vacuum_freeze_db |
| 29 | `sim_gen_cascade_payments_db_006` | Dependency cascade — payments_db is cpu_throttled, surfacing as alerts on checkout | 0.65 | 18 | platform.read_slack -> platform.describe_topology -> platform.get_logs -> platform.get_logs -> platform.get_trace -> platform.vacuum_freeze_db |
| 30 | `sim_gen_cascade_users_db_019` | Dependency cascade — users_db is degraded, surfacing as alerts on api_gateway | 0.65 | 18 | platform.read_slack -> platform.describe_topology -> platform.get_logs -> platform.get_logs -> platform.get_trace -> platform.vacuum_freeze_db |
| 31 | `sim_gen_cascade_users_db_020` | Dependency cascade — users_db is degraded, surfacing as alerts on api_gateway | 0.65 | 18 | platform.read_slack -> platform.describe_topology -> platform.get_logs -> platform.get_logs -> platform.get_trace -> platform.vacuum_freeze_db |
| 32 | `sim_gen_cascade_users_db_021` | Dependency cascade — users_db is memory_leak, surfacing as alerts on api_gateway | 0.65 | 18 | platform.read_slack -> platform.describe_topology -> platform.get_logs -> platform.get_logs -> platform.get_trace -> platform.vacuum_freeze_db |
| 33 | `sim_gen_cascade_users_db_022` | Dependency cascade — users_db is memory_leak, surfacing as alerts on api_gateway | 0.65 | 18 | platform.read_slack -> platform.describe_topology -> platform.get_logs -> platform.get_logs -> platform.get_trace -> platform.vacuum_freeze_db |
| 34 | `sim_gen_cascade_users_db_023` | Dependency cascade — users_db is cpu_throttled, surfacing as alerts on api_gateway | 0.65 | 18 | platform.read_slack -> platform.describe_topology -> platform.get_logs -> platform.get_logs -> platform.get_trace -> platform.vacuum_freeze_db |
| 35 | `sim_gen_cascade_users_db_024` | Dependency cascade — users_db is cpu_throttled, surfacing as alerts on api_gateway | 0.65 | 18 | platform.read_slack -> platform.describe_topology -> platform.get_logs -> platform.get_logs -> platform.get_trace -> platform.vacuum_freeze_db |
| 36 | `sim_gen_db_duel_orders_db_013` | Failover duel — saboteur attacks orders_db, then chokes orders_db_replica | 0.65 | 20 | platform.read_slack -> platform.get_logs -> platform.get_trace -> platform.failover_replica -> platform.read_slack -> platform.get_metrics -> platform.rollback_deployment |
| 37 | `sim_gen_db_duel_orders_db_014` | Failover duel — saboteur attacks orders_db, then chokes orders_db_replica | 0.65 | 20 | platform.read_slack -> platform.get_logs -> platform.get_trace -> platform.failover_replica -> platform.read_slack -> platform.get_metrics -> platform.rollback_deployment |
| 38 | `sim_gen_db_duel_orders_db_015` | Failover duel — saboteur attacks orders_db, then chokes orders_db_replica | 0.65 | 20 | platform.read_slack -> platform.get_logs -> platform.get_trace -> platform.failover_replica -> platform.read_slack -> platform.get_metrics -> platform.rollback_deployment |
| 39 | `sim_gen_db_duel_orders_db_016` | Failover duel — saboteur attacks orders_db, then chokes orders_db_replica | 0.65 | 20 | platform.read_slack -> platform.get_logs -> platform.get_trace -> platform.failover_replica -> platform.read_slack -> platform.get_metrics -> platform.rollback_deployment |
| 40 | `sim_gen_db_duel_orders_db_017` | Failover duel — saboteur attacks orders_db, then chokes orders_db_replica | 0.65 | 20 | platform.read_slack -> platform.get_logs -> platform.get_trace -> platform.failover_replica -> platform.read_slack -> platform.get_metrics -> platform.rollback_deployment |
| 41 | `sim_gen_db_duel_orders_db_018` | Failover duel — saboteur attacks orders_db, then chokes orders_db_replica | 0.65 | 20 | platform.read_slack -> platform.get_logs -> platform.get_trace -> platform.failover_replica -> platform.read_slack -> platform.get_metrics -> platform.rollback_deployment |
| 42 | `sim_gen_db_duel_orders_db_019` | Failover duel — saboteur attacks orders_db, then chokes orders_db_replica | 0.65 | 20 | platform.read_slack -> platform.get_logs -> platform.get_trace -> platform.failover_replica -> platform.read_slack -> platform.get_metrics -> platform.rollback_deployment |
| 43 | `sim_gen_db_duel_orders_db_020` | Failover duel — saboteur attacks orders_db, then chokes orders_db_replica | 0.65 | 20 | platform.read_slack -> platform.get_logs -> platform.get_trace -> platform.failover_replica -> platform.read_slack -> platform.get_metrics -> platform.rollback_deployment |
| 44 | `sim_gen_db_duel_orders_db_021` | Failover duel — saboteur attacks orders_db, then chokes orders_db_replica | 0.65 | 20 | platform.read_slack -> platform.get_logs -> platform.get_trace -> platform.failover_replica -> platform.read_slack -> platform.get_metrics -> platform.rollback_deployment |
| 45 | `sim_gen_db_duel_orders_db_022` | Failover duel — saboteur attacks orders_db, then chokes orders_db_replica | 0.65 | 20 | platform.read_slack -> platform.get_logs -> platform.get_trace -> platform.failover_replica -> platform.read_slack -> platform.get_metrics -> platform.rollback_deployment |
| 46 | `sim_gen_db_duel_orders_db_023` | Failover duel — saboteur attacks orders_db, then chokes orders_db_replica | 0.65 | 20 | platform.read_slack -> platform.get_logs -> platform.get_trace -> platform.failover_replica -> platform.read_slack -> platform.get_metrics -> platform.rollback_deployment |
| 47 | `sim_gen_db_duel_orders_db_024` | Failover duel — saboteur attacks orders_db, then chokes orders_db_replica | 0.65 | 20 | platform.read_slack -> platform.get_logs -> platform.get_trace -> platform.failover_replica -> platform.read_slack -> platform.get_metrics -> platform.rollback_deployment |
| 48 | `sim_gen_db_duel_users_db_001` | Failover duel — saboteur attacks users_db, then chokes users_db_replica | 0.65 | 20 | platform.read_slack -> platform.get_logs -> platform.get_trace -> platform.failover_replica -> platform.read_slack -> platform.get_metrics -> platform.rollback_deployment |
| 49 | `sim_gen_db_duel_users_db_002` | Failover duel — saboteur attacks users_db, then chokes users_db_replica | 0.65 | 20 | platform.read_slack -> platform.get_logs -> platform.get_trace -> platform.failover_replica -> platform.read_slack -> platform.get_metrics -> platform.rollback_deployment |
| 50 | `sim_gen_db_duel_users_db_003` | Failover duel — saboteur attacks users_db, then chokes users_db_replica | 0.65 | 20 | platform.read_slack -> platform.get_logs -> platform.get_trace -> platform.failover_replica -> platform.read_slack -> platform.get_metrics -> platform.rollback_deployment |
| 51 | `sim_gen_db_duel_users_db_004` | Failover duel — saboteur attacks users_db, then chokes users_db_replica | 0.65 | 20 | platform.read_slack -> platform.get_logs -> platform.get_trace -> platform.failover_replica -> platform.read_slack -> platform.get_metrics -> platform.rollback_deployment |
| 52 | `sim_gen_db_duel_users_db_005` | Failover duel — saboteur attacks users_db, then chokes users_db_replica | 0.65 | 20 | platform.read_slack -> platform.get_logs -> platform.get_trace -> platform.failover_replica -> platform.read_slack -> platform.get_metrics -> platform.rollback_deployment |
| 53 | `sim_gen_db_duel_users_db_006` | Failover duel — saboteur attacks users_db, then chokes users_db_replica | 0.65 | 20 | platform.read_slack -> platform.get_logs -> platform.get_trace -> platform.failover_replica -> platform.read_slack -> platform.get_metrics -> platform.rollback_deployment |
| 54 | `sim_gen_db_duel_users_db_007` | Failover duel — saboteur attacks users_db, then chokes users_db_replica | 0.65 | 20 | platform.read_slack -> platform.get_logs -> platform.get_trace -> platform.failover_replica -> platform.read_slack -> platform.get_metrics -> platform.rollback_deployment |
| 55 | `sim_gen_db_duel_users_db_008` | Failover duel — saboteur attacks users_db, then chokes users_db_replica | 0.65 | 20 | platform.read_slack -> platform.get_logs -> platform.get_trace -> platform.failover_replica -> platform.read_slack -> platform.get_metrics -> platform.rollback_deployment |
| 56 | `sim_gen_db_duel_users_db_009` | Failover duel — saboteur attacks users_db, then chokes users_db_replica | 0.65 | 20 | platform.read_slack -> platform.get_logs -> platform.get_trace -> platform.failover_replica -> platform.read_slack -> platform.get_metrics -> platform.rollback_deployment |
| 57 | `sim_gen_db_duel_users_db_010` | Failover duel — saboteur attacks users_db, then chokes users_db_replica | 0.65 | 20 | platform.read_slack -> platform.get_logs -> platform.get_trace -> platform.failover_replica -> platform.read_slack -> platform.get_metrics -> platform.rollback_deployment |
| 58 | `sim_gen_db_duel_users_db_011` | Failover duel — saboteur attacks users_db, then chokes users_db_replica | 0.65 | 20 | platform.read_slack -> platform.get_logs -> platform.get_trace -> platform.failover_replica -> platform.read_slack -> platform.get_metrics -> platform.rollback_deployment |
| 59 | `sim_gen_db_duel_users_db_012` | Failover duel — saboteur attacks users_db, then chokes users_db_replica | 0.65 | 20 | platform.read_slack -> platform.get_logs -> platform.get_trace -> platform.failover_replica -> platform.read_slack -> platform.get_metrics -> platform.rollback_deployment |
| 60 | `sim_gen_restore_catalog_db_005` | Corruption in catalog_db — restore vs rebuild trolley | 0.6 | 14 | platform.read_slack -> platform.get_logs -> platform.get_trace -> platform.search_runbook -> platform.restore_from_backup |
| 61 | `sim_gen_restore_catalog_db_006` | Corruption in catalog_db — restore vs rebuild trolley | 0.6 | 14 | platform.read_slack -> platform.get_logs -> platform.get_trace -> platform.search_runbook -> platform.restore_from_backup |
| 62 | `sim_gen_restore_inventory_db_003` | Corruption in inventory_db — restore vs rebuild trolley | 0.6 | 14 | platform.read_slack -> platform.get_logs -> platform.get_trace -> platform.search_runbook -> platform.restore_from_backup |
| 63 | `sim_gen_restore_inventory_db_004` | Corruption in inventory_db — restore vs rebuild trolley | 0.6 | 14 | platform.read_slack -> platform.get_logs -> platform.get_trace -> platform.search_runbook -> platform.restore_from_backup |
| 64 | `sim_gen_restore_orders_db_007` | Corruption in orders_db — restore vs rebuild trolley | 0.6 | 14 | platform.read_slack -> platform.get_logs -> platform.get_trace -> platform.search_runbook -> platform.restore_from_backup |
| 65 | `sim_gen_restore_orders_db_008` | Corruption in orders_db — restore vs rebuild trolley | 0.6 | 14 | platform.read_slack -> platform.get_logs -> platform.get_trace -> platform.search_runbook -> platform.restore_from_backup |
| 66 | `sim_gen_restore_payments_db_001` | Corruption in payments_db — restore vs rebuild trolley | 0.6 | 14 | platform.read_slack -> platform.get_logs -> platform.get_trace -> platform.search_runbook -> platform.restore_from_backup |
| 67 | `sim_gen_restore_payments_db_002` | Corruption in payments_db — restore vs rebuild trolley | 0.6 | 14 | platform.read_slack -> platform.get_logs -> platform.get_trace -> platform.search_runbook -> platform.restore_from_backup |
| 68 | `sim_hard_apigw_chain_001` | checkout 5xx — alert says ApiGateway | 0.65 | 22 | cloudwatch.get_logs -> lambda.invoke -> kms.describe -> kms.enable -> secretsmanager.describe -> secretsmanager.rotate -> lambda.invoke |
| 69 | `sim_hard_apigw_chain_002` | orders 5xx — alert says ApiGateway | 0.65 | 22 | cloudwatch.get_logs -> lambda.invoke -> kms.describe -> kms.enable -> secretsmanager.describe -> secretsmanager.rotate -> lambda.invoke |
| 70 | `sim_hard_apigw_chain_003` | inventory 5xx — alert says ApiGateway | 0.65 | 22 | cloudwatch.get_logs -> lambda.invoke -> kms.describe -> kms.enable -> secretsmanager.describe -> secretsmanager.rotate -> lambda.invoke |
| 71 | `sim_hard_apigw_chain_004` | payments 5xx — alert says ApiGateway | 0.65 | 22 | cloudwatch.get_logs -> lambda.invoke -> kms.describe -> kms.enable -> secretsmanager.describe -> secretsmanager.rotate -> lambda.invoke |
| 72 | `sim_hard_apigw_chain_005` | search 5xx — alert says ApiGateway | 0.65 | 22 | cloudwatch.get_logs -> lambda.invoke -> kms.describe -> kms.enable -> secretsmanager.describe -> secretsmanager.rotate -> lambda.invoke |
| 73 | `sim_hard_apigw_chain_006` | recommendations 5xx — alert says ApiGateway | 0.65 | 22 | cloudwatch.get_logs -> lambda.invoke -> kms.describe -> kms.enable -> secretsmanager.describe -> secretsmanager.rotate -> lambda.invoke |
| 74 | `sim_hard_apigw_chain_007` | auth 5xx — alert says ApiGateway | 0.65 | 22 | cloudwatch.get_logs -> lambda.invoke -> kms.describe -> kms.enable -> secretsmanager.describe -> secretsmanager.rotate -> lambda.invoke |
| 75 | `sim_hard_apigw_chain_008` | billing 5xx — alert says ApiGateway | 0.65 | 22 | cloudwatch.get_logs -> lambda.invoke -> kms.describe -> kms.enable -> secretsmanager.describe -> secretsmanager.rotate -> lambda.invoke |
| 76 | `sim_hard_apigw_chain_009` | shipping 5xx — alert says ApiGateway | 0.65 | 22 | cloudwatch.get_logs -> lambda.invoke -> kms.describe -> kms.enable -> secretsmanager.describe -> secretsmanager.rotate -> lambda.invoke |
| 77 | `sim_hard_apigw_chain_010` | notifications 5xx — alert says ApiGateway | 0.65 | 22 | cloudwatch.get_logs -> lambda.invoke -> kms.describe -> kms.enable -> secretsmanager.describe -> secretsmanager.rotate -> lambda.invoke |
| 78 | `sim_hard_ddb_chain_021` | checkout latency spike — alert says DDB throttle | 0.65 | 22 | cloudwatch.get_logs -> dynamodb.send -> ssm.diff_versions -> ssm.rollback -> dynamodb.scale -> lambda.invoke |
| 79 | `sim_hard_ddb_chain_022` | orders latency spike — alert says DDB throttle | 0.65 | 22 | cloudwatch.get_logs -> dynamodb.send -> ssm.diff_versions -> ssm.rollback -> dynamodb.scale -> lambda.invoke |
| 80 | `sim_hard_ddb_chain_023` | inventory latency spike — alert says DDB throttle | 0.65 | 22 | cloudwatch.get_logs -> dynamodb.send -> ssm.diff_versions -> ssm.rollback -> dynamodb.scale -> lambda.invoke |
| 81 | `sim_hard_ddb_chain_024` | payments latency spike — alert says DDB throttle | 0.65 | 22 | cloudwatch.get_logs -> dynamodb.send -> ssm.diff_versions -> ssm.rollback -> dynamodb.scale -> lambda.invoke |
| 82 | `sim_hard_ddb_chain_025` | search latency spike — alert says DDB throttle | 0.65 | 22 | cloudwatch.get_logs -> dynamodb.send -> ssm.diff_versions -> ssm.rollback -> dynamodb.scale -> lambda.invoke |
| 83 | `sim_hard_ddb_chain_026` | recommendations latency spike — alert says DDB throttle | 0.65 | 22 | cloudwatch.get_logs -> dynamodb.send -> ssm.diff_versions -> ssm.rollback -> dynamodb.scale -> lambda.invoke |
| 84 | `sim_hard_ddb_chain_027` | auth latency spike — alert says DDB throttle | 0.65 | 22 | cloudwatch.get_logs -> dynamodb.send -> ssm.diff_versions -> ssm.rollback -> dynamodb.scale -> lambda.invoke |
| 85 | `sim_hard_ddb_chain_028` | billing latency spike — alert says DDB throttle | 0.65 | 22 | cloudwatch.get_logs -> dynamodb.send -> ssm.diff_versions -> ssm.rollback -> dynamodb.scale -> lambda.invoke |
| 86 | `sim_hard_ddb_chain_029` | shipping latency spike — alert says DDB throttle | 0.65 | 22 | cloudwatch.get_logs -> dynamodb.send -> ssm.diff_versions -> ssm.rollback -> dynamodb.scale -> lambda.invoke |
| 87 | `sim_hard_ddb_chain_030` | notifications latency spike — alert says DDB throttle | 0.65 | 22 | cloudwatch.get_logs -> dynamodb.send -> ssm.diff_versions -> ssm.rollback -> dynamodb.scale -> lambda.invoke |
| 88 | `sim_hard_iam_chain_011` | checkout pipeline silent — alert says LambdaErrors | 0.65 | 22 | events.describe -> events.publish -> lambda.describe -> iam.simulate_policy -> lambda.put_policy -> events.publish -> lambda.invoke |
| 89 | `sim_hard_iam_chain_012` | orders pipeline silent — alert says LambdaErrors | 0.65 | 22 | events.describe -> events.publish -> lambda.describe -> iam.simulate_policy -> lambda.put_policy -> events.publish -> lambda.invoke |
| 90 | `sim_hard_iam_chain_013` | inventory pipeline silent — alert says LambdaErrors | 0.65 | 22 | events.describe -> events.publish -> lambda.describe -> iam.simulate_policy -> lambda.put_policy -> events.publish -> lambda.invoke |
| 91 | `sim_hard_iam_chain_014` | payments pipeline silent — alert says LambdaErrors | 0.65 | 22 | events.describe -> events.publish -> lambda.describe -> iam.simulate_policy -> lambda.put_policy -> events.publish -> lambda.invoke |
| 92 | `sim_hard_iam_chain_015` | search pipeline silent — alert says LambdaErrors | 0.65 | 22 | events.describe -> events.publish -> lambda.describe -> iam.simulate_policy -> lambda.put_policy -> events.publish -> lambda.invoke |
| 93 | `sim_hard_iam_chain_016` | recommendations pipeline silent — alert says LambdaErrors | 0.65 | 22 | events.describe -> events.publish -> lambda.describe -> iam.simulate_policy -> lambda.put_policy -> events.publish -> lambda.invoke |
| 94 | `sim_hard_iam_chain_017` | auth pipeline silent — alert says LambdaErrors | 0.65 | 22 | events.describe -> events.publish -> lambda.describe -> iam.simulate_policy -> lambda.put_policy -> events.publish -> lambda.invoke |
| 95 | `sim_hard_iam_chain_018` | billing pipeline silent — alert says LambdaErrors | 0.65 | 22 | events.describe -> events.publish -> lambda.describe -> iam.simulate_policy -> lambda.put_policy -> events.publish -> lambda.invoke |
| 96 | `sim_hard_iam_chain_019` | shipping pipeline silent — alert says LambdaErrors | 0.65 | 22 | events.describe -> events.publish -> lambda.describe -> iam.simulate_policy -> lambda.put_policy -> events.publish -> lambda.invoke |
| 97 | `sim_hard_iam_chain_020` | notifications pipeline silent — alert says LambdaErrors | 0.65 | 22 | events.describe -> events.publish -> lambda.describe -> iam.simulate_policy -> lambda.put_policy -> events.publish -> lambda.invoke |
