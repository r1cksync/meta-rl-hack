"""Generate the AWS service / action / error catalogs from aws-services.md.

Outputs three JSON files into ../catalogs/:
  * services.json   — one entry per AWS service (slug, display name, category, supported resources, common errors)
  * actions.json    — flat list of (service, verb) tuples plus parameters and which errors they may raise
  * errors.json     — error-code dictionary with retriable flag, severity, hint keyword, common services

Usage:
    python rl-agent/simulator/generators/gen_catalogs.py

Idempotent. Safe to re-run.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]            # incident-commander/
SERVICES_MD = ROOT.parent / "aws-services.md"          # repo root
OUT = Path(__file__).resolve().parents[1] / "catalogs"

# ---------------------------------------------------------------------------
# 1) services
# ---------------------------------------------------------------------------

# Map a substring in the display name to (slug, category, resources, errors).
# Handlers will look up the slug to dispatch a real-ish response. Anything
# not in this table falls back to a generic stub with `category="other"`.
SLUG_OVERRIDES: dict[str, tuple[str, str, list[str], list[str]]] = {
    "AWS Lambda":                          ("lambda",      "compute",   ["functions","layers","aliases","versions","event_source_mappings","permissions"], ["ResourceNotFoundException","ResourceConflictException","TooManyRequestsException","KMSAccessDeniedException","ServiceException","CodeStorageExceededException","InvalidParameterValueException","UnsupportedMediaTypeException","RequestEntityTooLargeException"]),
    "Amazon EC2":                          ("ec2",         "compute",   ["instances","volumes","security_groups","subnets","amis","snapshots","key_pairs"],     ["InsufficientInstanceCapacity","InstanceLimitExceeded","InvalidInstanceID.NotFound","UnauthorizedOperation","Client.RequestLimitExceeded"]),
    "Amazon EC2 Auto Scaling":             ("autoscaling", "compute",   ["groups","launch_configurations","scaling_policies","scheduled_actions"],              ["AlreadyExists","LimitExceeded","ScalingActivityInProgress","ResourceInUse"]),
    "AWS Fargate":                         ("fargate",     "compute",   ["tasks","capacity_providers"],                                                          ["ClusterNotFoundException","InvalidParameterException","TaskStoppedException"]),
    "Amazon Elastic Container Service (ECS)": ("ecs",      "compute",   ["clusters","services","task_definitions","tasks","container_instances"],               ["ClusterNotFoundException","ServiceNotFoundException","TaskNotFoundException","NoUpdateAvailableException"]),
    "Amazon Elastic Kubernetes Service (EKS)": ("eks",     "compute",   ["clusters","nodegroups","fargate_profiles","addons"],                                  ["ResourceNotFoundException","InvalidRequestException","ClientException","ServerException"]),
    "Amazon Elastic Container Registry (ECR)": ("ecr",     "compute",   ["repositories","images"],                                                              ["RepositoryNotFoundException","ImageNotFoundException","RepositoryAlreadyExistsException","TooManyRequestsException"]),
    "AWS Elastic Beanstalk":               ("elasticbeanstalk","compute",["applications","environments","versions"],                                            ["ResourceNotFoundException","TooManyEnvironmentsException"]),
    "AWS App Runner":                      ("apprunner",   "compute",   ["services","connections","auto_scaling_configurations"],                              ["ResourceNotFoundException","InvalidStateException","ServiceQuotaExceededException"]),
    "AWS Batch":                           ("batch",       "compute",   ["job_queues","job_definitions","jobs","compute_environments"],                       ["ClientException","ServerException"]),
    "Amazon Lightsail":                    ("lightsail",   "compute",   ["instances","databases","load_balancers","disks"],                                   ["NotFoundException","OperationFailureException"]),

    "Amazon Simple Storage Service (S3)":  ("s3",          "storage",   ["buckets","objects"],                                                                  ["NoSuchBucket","NoSuchKey","AccessDenied","BucketAlreadyExists","BucketNotEmpty","SlowDown","KMS.DisabledException","KMS.KeyUnavailableException"]),
    "Amazon Elastic Block Store (EBS)":    ("ebs",         "storage",   ["volumes","snapshots"],                                                                ["VolumeInUse","InvalidVolume.NotFound","SnapshotLimitExceeded"]),
    "Amazon Elastic File System (EFS)":    ("efs",         "storage",   ["file_systems","mount_targets","access_points"],                                       ["FileSystemNotFound","MountTargetNotFound","ThroughputLimitExceeded"]),
    "Amazon FSx":                          ("fsx",         "storage",   ["file_systems","backups","data_repository_associations"],                              ["FileSystemNotFound","BackupNotFound"]),
    "Amazon S3 Glacier":                   ("glacier",     "storage",   ["vaults","archives"],                                                                  ["ResourceNotFoundException","InvalidParameterValueException"]),
    "AWS Backup":                          ("backup",      "storage",   ["plans","vaults","jobs"],                                                              ["ResourceNotFoundException","InvalidParameterValueException"]),
    "AWS Storage Gateway":                 ("storagegateway","storage", ["gateways","volumes","tapes"],                                                         ["InvalidGatewayRequestException","InternalServerError"]),
    "AWS DataSync":                        ("datasync",    "storage",   ["tasks","locations","executions"],                                                     ["InvalidRequestException","InternalException"]),

    "Amazon Relational Database Service (RDS)": ("rds",   "database",  ["db_instances","db_clusters","snapshots","parameter_groups","subnet_groups"],         ["DBInstanceNotFound","DBClusterNotFoundFault","DBInstanceAlreadyExists","StorageQuotaExceeded","InsufficientDBInstanceCapacity"]),
    "Amazon Aurora":                       ("aurora",      "database",  ["db_clusters","snapshots","global_clusters"],                                          ["DBClusterNotFoundFault","InvalidDBClusterStateFault","StorageQuotaExceeded"]),
    "Amazon DynamoDB":                     ("dynamodb",    "database",  ["tables","global_secondary_indexes","streams","backups"],                              ["ResourceNotFoundException","ProvisionedThroughputExceededException","ThrottlingException","ConditionalCheckFailedException","TransactionConflictException","ValidationException","RequestLimitExceeded"]),
    "Amazon DocumentDB":                   ("docdb",       "database",  ["clusters","instances"],                                                                ["DBClusterNotFoundFault","InvalidDBClusterStateFault"]),
    "Amazon Neptune":                      ("neptune",     "database",  ["clusters","instances","loads"],                                                        ["DBClusterNotFoundFault"]),
    "Amazon ElastiCache":                  ("elasticache", "database",  ["clusters","replication_groups","snapshots","parameter_groups"],                       ["CacheClusterNotFoundFault","CacheClusterAlreadyExistsFault","NodeQuotaForCustomerExceededFault"]),
    "Amazon MemoryDB for Redis":           ("memorydb",    "database",  ["clusters","snapshots","users"],                                                        ["ClusterNotFoundFault","InvalidParameterValueException"]),
    "Amazon Keyspaces":                    ("keyspaces",   "database",  ["keyspaces","tables"],                                                                  ["ResourceNotFoundException","ConflictException"]),
    "Amazon Timestream":                   ("timestream",  "database",  ["databases","tables"],                                                                  ["ResourceNotFoundException","RejectedRecordsException"]),
    "Amazon QLDB":                         ("qldb",        "database",  ["ledgers","journals"],                                                                  ["ResourceNotFoundException","LimitExceededException"]),
    "Amazon Redshift":                     ("redshift",    "database",  ["clusters","snapshots","parameter_groups","users"],                                    ["ClusterNotFound","InvalidClusterState","InsufficientClusterCapacity"]),

    "Amazon Simple Queue Service (SQS)":   ("sqs",         "messaging", ["queues","messages"],                                                                  ["AWS.SimpleQueueService.NonExistentQueue","AWS.SimpleQueueService.QueueDeletedRecently","AWS.SimpleQueueService.PurgeQueueInProgress","OverLimit","KmsThrottled"]),
    "Amazon Simple Notification Service (SNS)": ("sns",   "messaging", ["topics","subscriptions","platform_applications"],                                     ["NotFoundException","AuthorizationErrorException","ThrottledException","FilterPolicyLimitExceededException"]),
    "Amazon EventBridge":                  ("events",      "messaging", ["event_buses","rules","targets","archives","schedules"],                               ["ResourceNotFoundException","InvalidEventPatternException","ManagedRuleException"]),
    "Amazon Managed Streaming for Apache Kafka (MSK)": ("kafka","messaging",["clusters","configurations","topics","consumer_groups"],                          ["NotFoundException","ServiceUnavailableException","TooManyRequestsException"]),
    "Amazon Kinesis Data Streams":         ("kinesis",     "messaging", ["streams","shards","consumers"],                                                        ["ResourceNotFoundException","ProvisionedThroughputExceededException","LimitExceededException"]),
    "Amazon Kinesis Data Firehose":        ("firehose",    "messaging", ["delivery_streams"],                                                                    ["ResourceNotFoundException","InvalidArgumentException","ServiceUnavailableException"]),
    "Amazon Kinesis Data Analytics":       ("kinesisanalytics","messaging",["applications","input_processing"],                                                  ["ResourceNotFoundException","InvalidApplicationConfigurationException"]),
    "Amazon Kinesis Video Streams":        ("kinesisvideo","messaging", ["streams","signaling_channels"],                                                        ["ResourceNotFoundException","ClientLimitExceededException"]),
    "Amazon MQ":                           ("mq",          "messaging", ["brokers","configurations","users"],                                                    ["NotFoundException","ConflictException"]),
    "Amazon Managed Workflows for Apache Airflow (MWAA)": ("mwaa","messaging",["environments"],                                                                  ["ResourceNotFoundException","AccessDeniedException"]),

    "AWS Identity and Access Management (IAM)": ("iam",   "security",  ["users","roles","policies","groups","instance_profiles","access_keys"],                ["NoSuchEntity","EntityAlreadyExists","DeleteConflict","LimitExceeded","MalformedPolicyDocument","UnmodifiableEntity"]),
    "AWS IAM Identity Center":             ("sso",         "security",  ["instances","permission_sets","accounts","groups"],                                    ["ResourceNotFoundException","ConflictException"]),
    "AWS Key Management Service (KMS)":    ("kms",         "security",  ["keys","aliases","grants"],                                                            ["NotFoundException","DisabledException","KMSInvalidStateException","KeyUnavailableException","KMSInternalException"]),
    "AWS Secrets Manager":                 ("secretsmanager","security",["secrets","rotation_lambdas"],                                                          ["ResourceNotFoundException","ResourceExistsException","DecryptionFailure","InvalidRequestException"]),
    "AWS Certificate Manager":             ("acm",         "security",  ["certificates"],                                                                       ["ResourceNotFoundException","RequestInProgressException"]),
    "AWS WAF":                             ("waf",         "security",  ["web_acls","rules","rule_groups","ip_sets"],                                            ["WAFNonexistentItemException","WAFLimitsExceededException"]),
    "AWS Shield":                          ("shield",      "security",  ["protections","subscriptions"],                                                         ["ResourceNotFoundException","InvalidPaginationTokenException"]),
    "AWS Firewall Manager":                ("fms",         "security",  ["policies","admin_accounts"],                                                           ["ResourceNotFoundException","InvalidOperationException"]),
    "Amazon GuardDuty":                    ("guardduty",   "security",  ["detectors","findings","ip_sets","threat_intel_sets"],                                 ["BadRequestException","InternalServerErrorException"]),
    "Amazon Inspector":                    ("inspector",   "security",  ["findings","assessments","filters"],                                                    ["NoSuchEntityException","AccessDeniedException"]),
    "Amazon Macie":                        ("macie",       "security",  ["findings","classification_jobs","custom_data_identifiers"],                           ["ResourceNotFoundException","ConflictException"]),
    "Amazon Detective":                    ("detective",   "security",  ["graphs","members"],                                                                    ["ResourceNotFoundException"]),
    "Amazon Cognito":                      ("cognito",     "security",  ["user_pools","identity_pools","clients"],                                              ["ResourceNotFoundException","UserNotFoundException","NotAuthorizedException","TooManyRequestsException"]),
    "AWS Security Hub":                    ("securityhub", "security",  ["standards","controls","findings","insights"],                                          ["ResourceNotFoundException","InvalidAccessException"]),
    "AWS Audit Manager":                   ("auditmanager","security",  ["assessments","frameworks","controls"],                                                 ["ResourceNotFoundException"]),
    "AWS Verified Permissions":            ("verifiedpermissions","security",["policy_stores","policies","schemas"],                                             ["ResourceNotFoundException","ConflictException"]),
    "AWS Verified Access":                 ("verifiedaccess","security",["instances","groups","endpoints"],                                                      ["ResourceNotFoundException"]),
    "AWS CloudHSM":                        ("cloudhsm",    "security",  ["clusters","hsms"],                                                                     ["CloudHsmResourceNotFoundException","CloudHsmInternalFailureException"]),
    "AWS Private CA":                      ("acmpca",      "security",  ["certificate_authorities","certificates"],                                              ["ResourceNotFoundException","RequestInProgressException"]),
    "AWS Payment Cryptography":            ("paymentcryptography","security",["keys","aliases"],                                                                  ["ResourceNotFoundException"]),
    "AWS Directory Service":               ("ds",          "security",  ["directories","trusts","conditional_forwarders"],                                       ["DirectoryNotShared","EntityDoesNotExistException"]),

    "AWS CloudTrail":                      ("cloudtrail",  "monitoring",["trails","event_data_stores","channels"],                                              ["TrailNotFoundException","InsufficientS3BucketPolicyException"]),
    "Amazon CloudWatch":                   ("cloudwatch",  "monitoring",["alarms","metrics","dashboards","log_groups","log_streams","insights_queries"],         ["ResourceNotFound","InvalidParameterValueException","LimitExceededException"]),
    "AWS X-Ray":                           ("xray",        "monitoring",["traces","groups","sampling_rules"],                                                    ["InvalidRequestException","RuleLimitExceededException"]),
    "Amazon Managed Grafana":              ("grafana",     "monitoring",["workspaces","data_sources","dashboards"],                                              ["ResourceNotFoundException","ConflictException"]),
    "Amazon Managed Prometheus":           ("amp",         "monitoring",["workspaces","rule_groups","alerting_rules"],                                          ["ResourceNotFoundException","ValidationException"]),
    "AWS Config":                          ("config",      "monitoring",["rules","resources","remediation_configurations"],                                      ["NoSuchConfigRuleException","NoSuchBucketException"]),
    "AWS Health Dashboard":                ("health",      "monitoring",["events","entities"],                                                                  ["InvalidPaginationToken"]),
    "Amazon DevOps Guru":                  ("devopsguru",  "monitoring",["insights","anomalies","resources"],                                                    ["ResourceNotFoundException"]),
    "AWS Trusted Advisor":                 ("trustedadvisor","monitoring",["checks","check_results"],                                                            ["InvalidParameterValueException"]),
    "AWS Compute Optimizer":               ("computeoptimizer","monitoring",["recommendations"],                                                                  ["ResourceNotFoundException"]),

    "Amazon Route 53":                     ("route53",     "networking",["hosted_zones","records","health_checks","domains"],                                   ["NoSuchHostedZone","NoSuchHealthCheck","HostedZoneAlreadyExists"]),
    "Amazon VPC":                          ("vpc",         "networking",["vpcs","subnets","route_tables","internet_gateways","nat_gateways","peering_connections","endpoints"], ["VpcLimitExceeded","InvalidVpcID.NotFound","DependencyViolation"]),
    "AWS PrivateLink":                     ("privatelink", "networking",["endpoints","endpoint_services"],                                                       ["VpcEndpointLimitExceeded","InvalidServiceName"]),
    "AWS Direct Connect":                  ("directconnect","networking",["connections","virtual_interfaces","gateways"],                                       ["DirectConnectClientException","DirectConnectServerException"]),
    "AWS Transit Gateway":                 ("transitgateway","networking",["transit_gateways","attachments","route_tables"],                                    ["TransitGatewayLimitExceeded"]),
    "Amazon CloudFront":                   ("cloudfront",  "networking",["distributions","origin_access_identities","cache_policies","functions"],              ["NoSuchDistribution","DistributionNotDisabled","TooManyDistributions","InvalidArgument"]),
    "Amazon API Gateway":                  ("apigateway",  "networking",["rest_apis","resources","methods","stages","deployments","authorizers","usage_plans"], ["NotFoundException","ConflictException","TooManyRequestsException","UnauthorizedException"]),
    "AWS App Mesh":                        ("appmesh",     "networking",["meshes","virtual_nodes","virtual_routers","routes"],                                  ["NotFoundException","ConflictException"]),
    "AWS Global Accelerator":              ("globalaccelerator","networking",["accelerators","listeners","endpoint_groups"],                                     ["AcceleratorNotFoundException","ListenerNotFoundException"]),
    "AWS VPN":                             ("vpn",         "networking",["connections","gateways"],                                                              ["VpnConnectionLimitExceeded"]),
    "AWS Network Firewall":                ("networkfirewall","networking",["firewalls","rule_groups","policies"],                                              ["ResourceNotFoundException"]),
    "AWS Cloud Map":                       ("servicediscovery","networking",["namespaces","services","instances"],                                              ["NamespaceNotFound","ServiceNotFound"]),

    "AWS Step Functions":                  ("stepfunctions","integration",["state_machines","executions","activities"],                                          ["StateMachineDoesNotExist","ExecutionDoesNotExist","StateMachineLimitExceeded","States.TaskFailed","States.Timeout"]),
    "AWS AppSync":                         ("appsync",     "integration",["graphql_apis","data_sources","resolvers","functions"],                               ["NotFoundException","ConflictException"]),
    "Amazon AppFlow":                      ("appflow",     "integration",["flows","connector_profiles","executions"],                                            ["ResourceNotFoundException","ConflictException"]),
    "AWS Data Pipeline":                   ("datapipeline","integration",["pipelines","tasks"],                                                                  ["PipelineNotFoundException"]),
    "Amazon Connect":                      ("connect",     "integration",["instances","contact_flows","queues","users"],                                        ["ResourceNotFoundException","ServiceQuotaExceededException"]),

    "Amazon SageMaker":                    ("sagemaker",   "ai_ml",     ["endpoints","training_jobs","models","notebooks","domains","pipelines"],               ["ResourceNotFound","ResourceLimitExceeded","ResourceInUse"]),
    "Amazon Bedrock":                      ("bedrock",     "ai_ml",     ["foundation_models","custom_models","model_invocations","guardrails","agents"],         ["ThrottlingException","AccessDeniedException","ValidationException","ModelTimeoutException"]),
    "Amazon Comprehend":                   ("comprehend",  "ai_ml",     ["entities_detection_jobs","key_phrases_jobs","classifiers"],                            ["ResourceNotFoundException","TooManyRequestsException"]),
    "Amazon Rekognition":                  ("rekognition", "ai_ml",     ["collections","faces","stream_processors","projects"],                                 ["ResourceNotFoundException","ImageTooLargeException"]),
    "Amazon Polly":                        ("polly",       "ai_ml",     ["voices","lexicons","synthesis_tasks"],                                                 ["LexiconNotFoundException","ServiceFailureException"]),
    "Amazon Textract":                     ("textract",    "ai_ml",     ["jobs","documents"],                                                                    ["InvalidJobIdException","ProvisionedThroughputExceededException"]),
    "Amazon Transcribe":                   ("transcribe",  "ai_ml",     ["transcription_jobs","vocabularies","language_models"],                                 ["NotFoundException","BadRequestException"]),
    "Amazon Translate":                    ("translate",   "ai_ml",     ["text","jobs","custom_terminologies"],                                                  ["ResourceNotFoundException","TextSizeLimitExceededException"]),
    "Amazon Lex":                          ("lex",         "ai_ml",     ["bots","intents","slots","aliases"],                                                    ["NotFoundException","ConflictException"]),
    "Amazon Kendra":                       ("kendra",      "ai_ml",     ["indexes","data_sources","faqs"],                                                       ["ResourceNotFoundException","ServiceQuotaExceededException"]),
    "Amazon Personalize":                  ("personalize", "ai_ml",     ["solutions","campaigns","datasets","recommenders"],                                     ["ResourceNotFoundException"]),
    "Amazon Forecast":                     ("forecast",    "ai_ml",     ["predictors","forecasts","datasets"],                                                   ["ResourceNotFoundException","LimitExceededException"]),
    "Amazon Fraud Detector":               ("frauddetector","ai_ml",    ["detectors","models","outcomes"],                                                       ["ResourceNotFoundException"]),
    "Amazon Q":                            ("q",           "ai_ml",     ["applications","retrievers","chats"],                                                   ["ResourceNotFoundException"]),
    "Amazon Comprehend Medical":           ("comprehendmedical","ai_ml",["entities_detection","icd10cm_inference"],                                              ["TooManyRequestsException"]),
    "Amazon Lookout for Equipment":        ("lookoutequipment","ai_ml", ["models","datasets","inferences"],                                                       ["ResourceNotFoundException"]),
    "Amazon Lookout for Metrics":          ("lookoutmetrics","ai_ml",   ["anomaly_detectors","metric_sets"],                                                     ["ResourceNotFoundException"]),
    "Amazon Lookout for Vision":           ("lookoutvision","ai_ml",    ["projects","models","datasets"],                                                        ["ResourceNotFoundException"]),

    "AWS Glue":                            ("glue",        "analytics", ["databases","tables","crawlers","jobs","triggers","workflows"],                         ["EntityNotFoundException","ConcurrentRunsExceededException","ResourceNumberLimitExceededException"]),
    "Amazon Athena":                       ("athena",      "analytics", ["workgroups","named_queries","query_executions","data_catalogs"],                       ["InvalidRequestException","TooManyRequestsException","InternalServerException"]),
    "Amazon EMR":                          ("emr",         "analytics", ["clusters","instance_groups","steps"],                                                   ["InvalidRequestException","InternalServerException"]),
    "AWS Lake Formation":                  ("lakeformation","analytics",["resources","permissions","data_lake_settings"],                                        ["EntityNotFoundException","AccessDeniedException"]),
    "Amazon QuickSight":                   ("quicksight",  "analytics", ["analyses","dashboards","datasets","data_sources","themes"],                            ["ResourceNotFoundException","ConflictException"]),
    "Amazon OpenSearch Service":           ("opensearch",  "analytics", ["domains","collections","packages"],                                                    ["ResourceNotFoundException","DisabledOperationException"]),
    "AWS Data Exchange":                   ("dataexchange","analytics", ["data_sets","revisions","jobs"],                                                        ["ResourceNotFoundException"]),
    "Amazon FinSpace":                     ("finspace",    "analytics", ["environments","users","datasets"],                                                     ["ResourceNotFoundException"]),
    "AWS Clean Rooms":                     ("cleanrooms",  "analytics", ["collaborations","memberships","configured_tables"],                                    ["ResourceNotFoundException","ConflictException"]),
    "Amazon DataZone":                     ("datazone",    "analytics", ["domains","projects","environments"],                                                   ["ResourceNotFoundException"]),
    "Amazon CloudSearch":                  ("cloudsearch", "analytics", ["domains","analysis_schemes"],                                                          ["ResourceNotFound","BaseException"]),
    "Amazon Security Lake":                ("securitylake","analytics", ["data_lakes","subscribers","sources"],                                                  ["ResourceNotFoundException"]),

    "AWS Systems Manager":                 ("ssm",         "management",["parameters","documents","run_commands","sessions","patches","automations"],          ["ParameterNotFound","ParameterAlreadyExists","InvalidDocument","InvalidInstanceId","TooManyUpdates"]),
    "AWS CloudFormation":                  ("cloudformation","management",["stacks","change_sets","stack_sets","templates","resources"],                       ["AlreadyExistsException","StackInstanceNotFoundException","ChangeSetNotFound","InsufficientCapabilitiesException"]),
    "AWS Service Catalog":                 ("servicecatalog","management",["portfolios","products","provisioned_products"],                                     ["ResourceNotFoundException","InvalidParametersException"]),
    "AWS Auto Scaling":                    ("applicationautoscaling","management",["targets","policies"],                                                       ["ObjectNotFoundException","LimitExceededException"]),
    "AWS Application Auto Scaling":        ("appautoscaling","management",["targets","policies","scheduled_actions"],                                           ["ObjectNotFoundException"]),
    "AWS Organizations":                   ("organizations","management",["accounts","organizational_units","policies","roots"],                                ["AccountNotFoundException","ConcurrentModificationException"]),
    "AWS Control Tower":                   ("controltower","management",["landing_zones","controls","baselines"],                                                ["ResourceNotFoundException"]),
    "AWS Resource Access Manager (RAM)":   ("ram",         "management",["resource_shares","invitations","permissions"],                                        ["UnknownResourceException","ResourceShareLimitExceededException"]),
    "AWS Proton":                          ("proton",      "management",["templates","environments","services"],                                                ["ResourceNotFoundException"]),
    "AWS Resilience Hub":                  ("resiliencehub","management",["apps","resiliency_policies","assessments"],                                          ["ResourceNotFoundException"]),
    "AWS License Manager":                 ("licensemanager","management",["license_configurations","licenses"],                                                ["InvalidParameterValueException"]),
    "AWS Launch Wizard":                   ("launchwizard","management",["deployments"],                                                                        ["ValidationException"]),
    "AWS Migration Hub":                   ("migrationhub","management",["progress_updates","migration_tasks"],                                                  ["UnauthorizedOperation"]),

    "AWS CodeBuild":                       ("codebuild",   "devtools",  ["projects","builds","build_batches","reports"],                                         ["ResourceNotFoundException","InvalidInputException"]),
    "AWS CodeCommit":                      ("codecommit",  "devtools",  ["repositories","branches","commits","pull_requests"],                                  ["RepositoryDoesNotExistException","BranchDoesNotExistException"]),
    "AWS CodeDeploy":                      ("codedeploy",  "devtools",  ["applications","deployment_groups","deployments"],                                     ["ApplicationDoesNotExistException","DeploymentDoesNotExistException"]),
    "AWS CodePipeline":                    ("codepipeline","devtools",  ["pipelines","actions","stages","webhooks"],                                            ["PipelineNotFoundException","StageNotFoundException"]),
    "AWS CodeArtifact":                    ("codeartifact","devtools",  ["domains","repositories","packages"],                                                  ["ResourceNotFoundException","ConflictException"]),
    "AWS CodeStar":                        ("codestar",    "devtools",  ["projects","team_members","user_profiles"],                                            ["ProjectNotFoundException"]),
    "AWS Cloud9":                          ("cloud9",      "devtools",  ["environments","memberships"],                                                          ["NotFoundException"]),
    "AWS CloudShell":                      ("cloudshell",  "devtools",  ["sessions"],                                                                            ["ResourceNotFoundException"]),
    "AWS Device Farm":                     ("devicefarm",  "devtools",  ["projects","runs","tests","jobs"],                                                      ["NotFoundException","ServiceAccountException"]),

    "AWS Amplify":                         ("amplify",     "frontend",  ["apps","branches","domains","backend_environments"],                                   ["NotFoundException","BadRequestException","UnauthorizedException"]),
    "Amazon AppStream 2.0":                ("appstream",   "frontend",  ["fleets","stacks","sessions","images"],                                                ["ResourceNotFoundException","OperationNotPermittedException"]),
    "Amazon WorkSpaces":                   ("workspaces",  "frontend",  ["workspaces","directories","bundles"],                                                  ["ResourceNotFoundException","InvalidParameterValuesException"]),
    "Amazon WorkDocs":                     ("workdocs",    "frontend",  ["folders","documents","users"],                                                         ["EntityNotExistsException"]),
    "Amazon WorkMail":                     ("workmail",    "frontend",  ["organizations","users","groups","aliases"],                                            ["EntityNotFoundException"]),

    "Amazon SES":                          ("ses",         "engagement",["identities","configuration_sets","templates"],                                         ["MessageRejected","MailFromDomainNotVerified","ConfigurationSetDoesNotExistException"]),
    "Amazon Simple Email Service (SES)":   ("ses",         "engagement",["identities","configuration_sets","templates"],                                         ["MessageRejected","MailFromDomainNotVerified"]),
    "Amazon Pinpoint":                     ("pinpoint",    "engagement",["apps","campaigns","journeys","segments"],                                              ["NotFoundException","BadRequestException"]),
    "Amazon Chime":                        ("chime",       "engagement",["meetings","attendees","accounts"],                                                     ["NotFoundException","ForbiddenException"]),
    "Amazon Chime SDK":                    ("chimesdk",    "engagement",["meetings","media_pipelines","voice_connectors"],                                       ["NotFoundException"]),
    "AWS Chatbot":                         ("chatbot",     "engagement",["chime_webhooks","slack_channels"],                                                     ["DescribeChimeWebhookConfigurationsException"]),
    "AWS Wickr":                           ("wickr",       "engagement",["networks"],                                                                           ["ResourceNotFoundException"]),
    "Amazon Connect":                      ("connect",     "engagement",["instances","contact_flows","queues","users"],                                          ["ResourceNotFoundException","DuplicateResourceException"]),

    "AWS IoT Core":                        ("iot",         "iot",       ["things","certificates","policies","topics","jobs"],                                   ["ResourceNotFoundException","ThrottlingException"]),
    "AWS IoT Analytics":                   ("iotanalytics","iot",       ["channels","datastores","pipelines","datasets"],                                       ["ResourceNotFoundException"]),
    "AWS IoT Device Defender":             ("iotdevicedefender","iot",  ["audit_findings","scheduled_audits"],                                                   ["ResourceNotFoundException"]),
    "AWS IoT Device Management":           ("iotdevicemanagement","iot",["fleets","jobs","groups"],                                                              ["ResourceNotFoundException"]),
    "AWS IoT Events":                      ("iotevents",   "iot",       ["detector_models","alarms","inputs"],                                                  ["ResourceNotFoundException"]),
    "AWS IoT FleetWise":                   ("iotfleetwise","iot",       ["fleets","vehicles","campaigns"],                                                       ["ResourceNotFoundException"]),
    "AWS IoT Greengrass":                  ("greengrass",  "iot",       ["core_devices","components","deployments"],                                            ["ResourceNotFoundException"]),
    "AWS IoT SiteWise":                    ("iotsitewise", "iot",       ["assets","models","gateways","portals"],                                               ["ResourceNotFoundException"]),
    "AWS IoT TwinMaker":                   ("iottwinmaker","iot",       ["workspaces","scenes","entities"],                                                     ["ResourceNotFoundException"]),

    "Amazon GameLift":                     ("gamelift",    "gametech",  ["fleets","game_sessions","aliases","matchmaking_configurations"],                       ["NotFoundException","FleetCapacityExceededException"]),
    "Amazon Nimble Studio":                ("nimble",      "media",     ["studios","launch_profiles","streaming_sessions"],                                      ["ResourceNotFoundException"]),
    "Amazon Interactive Video Service (IVS)": ("ivs",     "media",     ["channels","streams","recordings"],                                                     ["ResourceNotFoundException"]),
    "AWS Elemental MediaConnect":          ("mediaconnect","media",     ["flows","outputs","sources"],                                                          ["NotFoundException"]),
    "AWS Elemental MediaConvert":          ("mediaconvert","media",     ["jobs","queues","presets","templates"],                                                ["NotFoundException","ConflictException"]),
    "AWS Elemental MediaLive":             ("medialive",   "media",     ["channels","inputs","schedules"],                                                      ["NotFoundException","UnprocessableEntityException"]),
    "AWS Elemental MediaPackage":          ("mediapackage","media",     ["channels","origin_endpoints"],                                                        ["NotFoundException"]),
    "AWS Elemental MediaStore":            ("mediastore",  "media",     ["containers","items"],                                                                 ["ContainerNotFoundException"]),
    "AWS Elemental MediaTailor":           ("mediatailor", "media",     ["playback_configurations","channels"],                                                 ["BadRequestException"]),
    "Amazon Elastic Transcoder":           ("elastictranscoder","media",["pipelines","jobs","presets"],                                                          ["ResourceNotFoundException"]),

    "Amazon Braket":                       ("braket",      "quantum",   ["devices","quantum_tasks"],                                                            ["ResourceNotFoundException","ServiceQuotaExceededException"]),
    "AWS RoboMaker":                       ("robomaker",   "robotics",  ["robots","fleets","simulations","worlds"],                                              ["ResourceNotFoundException"]),
    "AWS Ground Station":                  ("groundstation","satellite",["mission_profiles","contacts","data_flow_endpoint_groups"],                            ["ResourceNotFoundException"]),
    "AWS DeepRacer":                       ("deepracer",   "ai_ml",     ["models","tracks","leaderboards"],                                                     ["ResourceNotFoundException"]),
    "AWS DeepLens":                        ("deeplens",    "ai_ml",     ["devices","projects","models"],                                                        ["ResourceNotFoundException"]),
    "AWS DeepComposer":                    ("deepcomposer","ai_ml",     ["compositions","models"],                                                              ["ResourceNotFoundException"]),
    "AWS Panorama":                        ("panorama",    "ai_ml",     ["devices","application_instances"],                                                    ["ResourceNotFoundException"]),
    "Amazon HealthLake":                   ("healthlake",  "healthcare",["fhir_datastores","import_jobs","export_jobs"],                                        ["ResourceNotFoundException"]),
    "AWS HealthImaging":                   ("healthimaging","healthcare",["data_stores","import_jobs"],                                                          ["ResourceNotFoundException"]),
    "Amazon Omics":                        ("omics",       "healthcare",["sequence_stores","reference_stores","workflows","runs"],                              ["ResourceNotFoundException"]),
    "Amazon Monitron":                     ("monitron",    "iot",       ["projects","sites","sensors","assets"],                                                ["ResourceNotFoundException"]),
    "AWS SimSpace Weaver":                 ("simspaceweaver","gametech",["simulations"],                                                                         ["ResourceNotFoundException"]),
    "AWS Mainframe Modernization":         ("mainframe",   "migration", ["applications","environments"],                                                        ["ResourceNotFoundException"]),
    "AWS Database Migration Service":      ("dms",         "migration", ["replication_instances","replication_tasks","endpoints"],                              ["ResourceNotFoundFault","InvalidResourceStateFault"]),
    "AWS Application Migration Service":   ("mgn",         "migration", ["source_servers","jobs","launch_configurations"],                                      ["ResourceNotFoundException"]),
    "AWS Application Discovery Service":   ("discovery",   "migration", ["agents","applications","configurations"],                                              ["ResourceNotFoundException"]),
    "AWS Elastic Disaster Recovery":       ("drs",         "migration", ["source_servers","recovery_instances","jobs"],                                          ["ResourceNotFoundException"]),
    "AWS Snow Family":                     ("snow",        "edge",      ["jobs","clusters"],                                                                    ["InvalidJobStateException"]),
    "AWS Snowball":                        ("snowball",    "edge",      ["jobs"],                                                                               ["InvalidJobStateException"]),
    "AWS Snowcone":                        ("snowcone",    "edge",      ["jobs"],                                                                               ["InvalidJobStateException"]),
    "AWS Snowmobile":                      ("snowmobile",  "edge",      ["jobs"],                                                                               ["InvalidJobStateException"]),
    "AWS Outposts":                        ("outposts",    "edge",      ["sites","outposts","orders"],                                                          ["NotFoundException"]),
    "AWS Wavelength":                      ("wavelength",  "edge",      ["zones","carrier_gateways"],                                                            ["NotFoundException"]),
    "AWS Local Zones":                     ("localzones",  "edge",      ["zones"],                                                                              ["NotFoundException"]),
    "Amazon Location Service":             ("location",    "frontend",  ["maps","place_indexes","route_calculators","trackers","geofence_collections"],         ["ResourceNotFoundException"]),
    "AWS Transfer Family":                 ("transfer",    "storage",   ["servers","users","workflows"],                                                        ["ResourceNotFoundException","InvalidRequestException"]),
    "Amazon VPC Lattice":                  ("vpclattice",  "networking",["service_networks","services","listeners","target_groups"],                            ["ResourceNotFoundException"]),
    "AWS Telco Network Builder":           ("tnb",         "networking",["sol_function_packages","sol_network_packages","instances"],                           ["ValidationException"]),
    "AWS Fault Injection Simulator":       ("fis",         "monitoring",["experiments","experiment_templates","actions"],                                       ["ResourceNotFoundException"]),
    "AWS OpsWorks":                        ("opsworks",    "management",["stacks","layers","instances","apps"],                                                  ["ResourceNotFoundException","ValidationException"]),
    "AWS Billing and Cost Management":     ("billing",     "billing",   ["bills","payments","tax_settings"],                                                    ["ValidationException"]),
    "AWS Cost Explorer":                   ("ce",          "billing",   ["cost_and_usage","forecasts","savings_plans"],                                         ["DataUnavailableException","LimitExceededException"]),
    "AWS Application Cost Profiler":       ("applicationcostprofiler","billing",["report_definitions"],                                                          ["ResourceNotFoundException"]),
    "AWS Marketplace":                     ("marketplace", "billing",   ["entitlements","subscriptions","products"],                                            ["ThrottlingException"]),
    "AWS Artifact":                        ("artifact",    "compliance",["reports","agreements"],                                                               ["AccessDeniedException"]),
    "AWS Managed Services":                ("ams",         "management",["stacks","change_requests"],                                                          ["ValidationException"]),
    "AWS Serverless Application Repository": ("serverlessrepo","compute",["applications","versions"],                                                          ["NotFoundException"]),
    "Amazon Supply Chain":                 ("supplychain", "industry",  ["instances","data_lake_datasets"],                                                     ["ResourceNotFoundException"]),
    "AWS Supply Chain":                    ("supplychain", "industry",  ["instances","data_lake_datasets"],                                                     ["ResourceNotFoundException"]),
    "AWS Entity Resolution":               ("entityresolution","ai_ml", ["matching_workflows","schema_mappings"],                                                ["ResourceNotFoundException"]),
    "Amazon Honeycode":                    ("honeycode",   "frontend",  ["workbooks","tables","screens"],                                                       ["ResourceNotFoundException"]),
    "Red Hat OpenShift Service on AWS (ROSA)": ("rosa",   "compute",   ["clusters","machine_pools"],                                                            ["ClusterNotFoundException"]),
    "Elastic Fabric Adapter":              ("efa",         "networking",["devices"],                                                                            ["ResourceNotFoundException"]),
    "Amazon Corretto":                     ("corretto",    "compute",   ["distributions"],                                                                       []),
    "Amazon Data Lifecycle Manager":       ("dlm",         "storage",   ["lifecycle_policies"],                                                                  ["ResourceNotFoundException"]),
    "AWS Well-Architected Tool":           ("wellarchitected","management",["workloads","lenses","reviews"],                                                     ["ResourceNotFoundException"]),
    "Amazon Managed Blockchain":           ("managedblockchain","blockchain",["networks","members","nodes"],                                                     ["ResourceNotFoundException"]),
    "AWS Partner Network":                 ("apn",         "marketplace",["opportunities","leads"],                                                              []),
}

# Services that are GUI/dashboards or marketing pages — no programmatic API
# surface worth simulating. Generator skips these.
DENYLIST = {
    "AWS Management Console",
    "AWS Marketplace",
    "AWS Health Dashboard",
    "AWS Partner Network",
    "Amazon Honeycode",
    "Amazon WorkLink",
    "Amazon Corretto",
}


def _slug(line: str) -> str:
    s = SLUG_OVERRIDES.get(line)
    if s:
        return s[0]
    # Fallback: lowercase, strip prefixes, alnum only.
    name = re.sub(r"^(AWS|Amazon)\s+", "", line).strip()
    name = re.sub(r"\(.*?\)", "", name).strip()
    return re.sub(r"[^a-zA-Z0-9]", "", name).lower() or "unknown"


# ---------------------------------------------------------------------------
# 2) operations — generic verb set, expanded per category
# ---------------------------------------------------------------------------

# Each verb has a kind: read | write | mutate | poll. May raise the error
# codes listed in `default_errors` (plus service-specific ones).
GENERIC_VERBS: list[dict] = [
    {"verb": "list",                 "kind": "read",    "params": ["filter","limit"],                  "default_errors": ["ThrottlingException","AccessDeniedException"]},
    {"verb": "describe",             "kind": "read",    "params": ["resource_id"],                    "default_errors": ["ResourceNotFoundException","AccessDeniedException"]},
    {"verb": "get",                  "kind": "read",    "params": ["resource_id"],                    "default_errors": ["ResourceNotFoundException","AccessDeniedException","ThrottlingException"]},
    {"verb": "get_tags",             "kind": "read",    "params": ["resource_id"],                    "default_errors": ["ResourceNotFoundException"]},
    {"verb": "list_tags",            "kind": "read",    "params": ["resource_id"],                    "default_errors": ["ResourceNotFoundException"]},
    {"verb": "head",                 "kind": "read",    "params": ["resource_id"],                    "default_errors": ["ResourceNotFoundException"]},
    {"verb": "list_versions",        "kind": "read",    "params": ["resource_id"],                    "default_errors": ["ResourceNotFoundException"]},
    {"verb": "get_policy",           "kind": "read",    "params": ["resource_id"],                    "default_errors": ["ResourceNotFoundException","AccessDeniedException"]},
    {"verb": "get_metrics",          "kind": "read",    "params": ["resource_id","range_minutes"],    "default_errors": ["ThrottlingException"]},
    {"verb": "get_logs",             "kind": "read",    "params": ["resource_id","range_minutes","filter"], "default_errors": ["ResourceNotFoundException","ThrottlingException"]},
    {"verb": "get_status",           "kind": "read",    "params": ["resource_id"],                    "default_errors": ["ResourceNotFoundException"]},
    {"verb": "get_quota",            "kind": "read",    "params": ["service_code"],                   "default_errors": ["NoSuchResourceException"]},
    {"verb": "list_events",          "kind": "read",    "params": ["resource_id","range_minutes"],    "default_errors": ["ThrottlingException"]},

    {"verb": "create",               "kind": "write",   "params": ["name","config"],                  "default_errors": ["ResourceAlreadyExistsException","LimitExceededException","AccessDeniedException"]},
    {"verb": "update",               "kind": "write",   "params": ["resource_id","config"],           "default_errors": ["ResourceNotFoundException","ConflictException","ThrottlingException"]},
    {"verb": "delete",               "kind": "write",   "params": ["resource_id"],                    "default_errors": ["ResourceNotFoundException","DependencyViolation","ConflictException"]},
    {"verb": "tag",                  "kind": "write",   "params": ["resource_id","tags"],             "default_errors": ["ResourceNotFoundException","TooManyTagsException"]},
    {"verb": "untag",                "kind": "write",   "params": ["resource_id","tag_keys"],         "default_errors": ["ResourceNotFoundException"]},
    {"verb": "put_policy",           "kind": "write",   "params": ["resource_id","policy"],           "default_errors": ["ResourceNotFoundException","MalformedPolicyDocument","AccessDeniedException"]},
    {"verb": "delete_policy",        "kind": "write",   "params": ["resource_id"],                    "default_errors": ["ResourceNotFoundException"]},
    {"verb": "start",                "kind": "write",   "params": ["resource_id","input"],            "default_errors": ["ResourceNotFoundException","InvalidStateException","TooManyRequestsException"]},
    {"verb": "stop",                 "kind": "write",   "params": ["resource_id"],                    "default_errors": ["ResourceNotFoundException","InvalidStateException"]},
    {"verb": "restart",              "kind": "write",   "params": ["resource_id"],                    "default_errors": ["ResourceNotFoundException","InvalidStateException"]},
    {"verb": "scale",                "kind": "write",   "params": ["resource_id","capacity"],         "default_errors": ["ResourceNotFoundException","LimitExceededException"]},
    {"verb": "rollback",             "kind": "write",   "params": ["resource_id","version"],          "default_errors": ["ResourceNotFoundException","InvalidStateException"]},
    {"verb": "pause",                "kind": "write",   "params": ["resource_id"],                    "default_errors": ["ResourceNotFoundException","InvalidStateException"]},
    {"verb": "resume",               "kind": "write",   "params": ["resource_id"],                    "default_errors": ["ResourceNotFoundException","InvalidStateException"]},
    {"verb": "rotate",               "kind": "write",   "params": ["resource_id"],                    "default_errors": ["ResourceNotFoundException","InvalidStateException"]},
    {"verb": "purge",                "kind": "write",   "params": ["resource_id"],                    "default_errors": ["ResourceNotFoundException","InvalidStateException"]},
    {"verb": "enable",               "kind": "write",   "params": ["resource_id"],                    "default_errors": ["ResourceNotFoundException"]},
    {"verb": "disable",              "kind": "write",   "params": ["resource_id"],                    "default_errors": ["ResourceNotFoundException"]},
    {"verb": "invoke",               "kind": "mutate",  "params": ["resource_id","payload"],          "default_errors": ["ResourceNotFoundException","TooManyRequestsException","KMSAccessDeniedException"]},
    {"verb": "publish",              "kind": "mutate",  "params": ["resource_id","payload"],          "default_errors": ["ResourceNotFoundException","TooManyRequestsException"]},
    {"verb": "send",                 "kind": "mutate",  "params": ["resource_id","payload"],          "default_errors": ["ResourceNotFoundException","TooManyRequestsException"]},
    {"verb": "receive",              "kind": "mutate",  "params": ["resource_id","limit"],            "default_errors": ["ResourceNotFoundException"]},
    {"verb": "encrypt",              "kind": "mutate",  "params": ["resource_id","plaintext"],        "default_errors": ["ResourceNotFoundException","KMSAccessDeniedException"]},
    {"verb": "decrypt",              "kind": "mutate",  "params": ["resource_id","ciphertext"],       "default_errors": ["ResourceNotFoundException","KMSAccessDeniedException"]},
    {"verb": "wait",                 "kind": "poll",    "params": ["resource_id","state"],            "default_errors": ["ResourceNotFoundException"]},
    {"verb": "simulate_policy",      "kind": "read",    "params": ["principal","action_name","resource"], "default_errors": ["NoSuchEntityException"]},
    {"verb": "diff_versions",        "kind": "read",    "params": ["resource_id","v1","v2"],          "default_errors": ["ResourceNotFoundException"]},
]


# ---------------------------------------------------------------------------
# 3) errors — reusable catalog
# ---------------------------------------------------------------------------

ERROR_CATALOG: dict[str, dict] = {
    # Generic AWS error families
    "ResourceNotFoundException":           {"retriable": False, "severity": "error",   "hint": "missing",      "http_status": 404},
    "ResourceAlreadyExistsException":      {"retriable": False, "severity": "warning", "hint": "duplicate",    "http_status": 409},
    "ConflictException":                   {"retriable": False, "severity": "warning", "hint": "conflict",     "http_status": 409},
    "AccessDeniedException":               {"retriable": False, "severity": "error",   "hint": "iam",          "http_status": 403},
    "UnauthorizedOperation":               {"retriable": False, "severity": "error",   "hint": "iam",          "http_status": 403},
    "ThrottlingException":                 {"retriable": True,  "severity": "warning", "hint": "throttle",     "http_status": 429},
    "TooManyRequestsException":            {"retriable": True,  "severity": "warning", "hint": "throttle",     "http_status": 429},
    "Client.RequestLimitExceeded":         {"retriable": True,  "severity": "warning", "hint": "throttle",     "http_status": 429},
    "ProvisionedThroughputExceededException": {"retriable": True, "severity": "warning","hint": "throttle",    "http_status": 400},
    "RequestLimitExceeded":                {"retriable": True,  "severity": "warning", "hint": "throttle",     "http_status": 429},
    "LimitExceededException":              {"retriable": False, "severity": "error",   "hint": "quota",        "http_status": 400},
    "LimitExceeded":                       {"retriable": False, "severity": "error",   "hint": "quota",        "http_status": 400},
    "ServiceQuotaExceededException":       {"retriable": False, "severity": "error",   "hint": "quota",        "http_status": 402},
    "OverLimit":                           {"retriable": False, "severity": "error",   "hint": "quota",        "http_status": 400},
    "InvalidParameterValueException":      {"retriable": False, "severity": "error",   "hint": "validation",   "http_status": 400},
    "InvalidParameterException":           {"retriable": False, "severity": "error",   "hint": "validation",   "http_status": 400},
    "ValidationException":                 {"retriable": False, "severity": "error",   "hint": "validation",   "http_status": 400},
    "MalformedPolicyDocument":             {"retriable": False, "severity": "error",   "hint": "policy",       "http_status": 400},
    "InvalidStateException":               {"retriable": False, "severity": "error",   "hint": "state",        "http_status": 409},
    "ServiceException":                    {"retriable": True,  "severity": "error",   "hint": "service",      "http_status": 500},
    "InternalServerException":             {"retriable": True,  "severity": "error",   "hint": "service",      "http_status": 500},
    "InternalServerError":                 {"retriable": True,  "severity": "error",   "hint": "service",      "http_status": 500},
    "DependencyViolation":                 {"retriable": False, "severity": "error",   "hint": "dependency",   "http_status": 400},
    "TooManyTagsException":                {"retriable": False, "severity": "warning", "hint": "tags",         "http_status": 400},
    "ResourceConflictException":           {"retriable": False, "severity": "warning", "hint": "conflict",     "http_status": 409},
    "InsufficientCapacity":                {"retriable": True,  "severity": "warning", "hint": "capacity",     "http_status": 503},
    "InsufficientInstanceCapacity":        {"retriable": True,  "severity": "warning", "hint": "capacity",     "http_status": 503},
    "ServiceUnavailableException":         {"retriable": True,  "severity": "error",   "hint": "service",      "http_status": 503},
    "ServiceUnavailable":                  {"retriable": True,  "severity": "error",   "hint": "service",      "http_status": 503},
    # KMS family
    "KMSAccessDeniedException":            {"retriable": False, "severity": "error",   "hint": "kms",          "http_status": 403},
    "KMSInvalidStateException":            {"retriable": False, "severity": "error",   "hint": "kms",          "http_status": 400},
    "KMS.DisabledException":               {"retriable": False, "severity": "error",   "hint": "kms",          "http_status": 400},
    "KMS.KeyUnavailableException":         {"retriable": True,  "severity": "error",   "hint": "kms",          "http_status": 500},
    "KMSInternalException":                {"retriable": True,  "severity": "error",   "hint": "kms",          "http_status": 500},
    "DecryptionFailure":                   {"retriable": False, "severity": "error",   "hint": "kms",          "http_status": 400},
    "KmsThrottled":                        {"retriable": True,  "severity": "warning", "hint": "throttle",     "http_status": 400},
    # Networking
    "VpcLimitExceeded":                    {"retriable": False, "severity": "error",   "hint": "quota",        "http_status": 400},
    "InvalidVpcID.NotFound":               {"retriable": False, "severity": "error",   "hint": "missing",      "http_status": 400},
    "InvalidServiceName":                  {"retriable": False, "severity": "error",   "hint": "validation",   "http_status": 400},
    "VpcEndpointLimitExceeded":            {"retriable": False, "severity": "error",   "hint": "quota",        "http_status": 400},
    "InvalidJobStateException":            {"retriable": False, "severity": "error",   "hint": "state",        "http_status": 400},
    "VolumeInUse":                         {"retriable": False, "severity": "warning", "hint": "state",        "http_status": 400},
    "InvalidVolume.NotFound":              {"retriable": False, "severity": "error",   "hint": "missing",      "http_status": 404},
    "SnapshotLimitExceeded":               {"retriable": False, "severity": "error",   "hint": "quota",        "http_status": 400},
    "InstanceLimitExceeded":               {"retriable": False, "severity": "error",   "hint": "quota",        "http_status": 400},
    "InvalidInstanceID.NotFound":          {"retriable": False, "severity": "error",   "hint": "missing",      "http_status": 404},
    "InvalidInstanceId":                   {"retriable": False, "severity": "error",   "hint": "missing",      "http_status": 404},
    "VpnConnectionLimitExceeded":          {"retriable": False, "severity": "error",   "hint": "quota",        "http_status": 400},
    "TransitGatewayLimitExceeded":         {"retriable": False, "severity": "error",   "hint": "quota",        "http_status": 400},
    # Storage / S3
    "NoSuchBucket":                        {"retriable": False, "severity": "error",   "hint": "missing",      "http_status": 404},
    "NoSuchKey":                           {"retriable": False, "severity": "error",   "hint": "missing",      "http_status": 404},
    "AccessDenied":                        {"retriable": False, "severity": "error",   "hint": "iam",          "http_status": 403},
    "BucketAlreadyExists":                 {"retriable": False, "severity": "warning", "hint": "duplicate",    "http_status": 409},
    "BucketNotEmpty":                      {"retriable": False, "severity": "warning", "hint": "state",        "http_status": 409},
    "SlowDown":                            {"retriable": True,  "severity": "warning", "hint": "throttle",     "http_status": 503},
    # Queues
    "AWS.SimpleQueueService.NonExistentQueue":     {"retriable": False, "severity": "error",   "hint": "missing",      "http_status": 400},
    "AWS.SimpleQueueService.QueueDeletedRecently": {"retriable": False, "severity": "warning", "hint": "state",        "http_status": 400},
    "AWS.SimpleQueueService.PurgeQueueInProgress": {"retriable": True,  "severity": "warning", "hint": "state",        "http_status": 403},
    # DDB family extras
    "ConditionalCheckFailedException":     {"retriable": False, "severity": "warning", "hint": "logic",        "http_status": 400},
    "TransactionConflictException":        {"retriable": True,  "severity": "warning", "hint": "conflict",     "http_status": 400},
    "ItemCollectionSizeLimitExceededException": {"retriable": False, "severity": "error", "hint": "quota",     "http_status": 400},
    # Lambda extras
    "CodeStorageExceededException":        {"retriable": False, "severity": "error",   "hint": "quota",        "http_status": 400},
    "RequestEntityTooLargeException":      {"retriable": False, "severity": "error",   "hint": "validation",   "http_status": 413},
    "UnsupportedMediaTypeException":       {"retriable": False, "severity": "error",   "hint": "validation",   "http_status": 415},
    # SFN
    "StateMachineDoesNotExist":            {"retriable": False, "severity": "error",   "hint": "missing",      "http_status": 400},
    "ExecutionDoesNotExist":               {"retriable": False, "severity": "error",   "hint": "missing",      "http_status": 400},
    "States.TaskFailed":                   {"retriable": False, "severity": "error",   "hint": "state",        "http_status": 400},
    "States.Timeout":                      {"retriable": True,  "severity": "warning", "hint": "timeout",      "http_status": 408},
    "StateMachineLimitExceeded":           {"retriable": False, "severity": "error",   "hint": "quota",        "http_status": 400},
    # IAM
    "NoSuchEntity":                        {"retriable": False, "severity": "error",   "hint": "missing",      "http_status": 404},
    "NoSuchEntityException":               {"retriable": False, "severity": "error",   "hint": "missing",      "http_status": 404},
    "EntityAlreadyExists":                 {"retriable": False, "severity": "warning", "hint": "duplicate",    "http_status": 409},
    "DeleteConflict":                      {"retriable": False, "severity": "warning", "hint": "dependency",   "http_status": 409},
    "UnmodifiableEntity":                  {"retriable": False, "severity": "warning", "hint": "state",        "http_status": 400},
    # Cognito
    "UserNotFoundException":               {"retriable": False, "severity": "error",   "hint": "missing",      "http_status": 404},
    "NotAuthorizedException":              {"retriable": False, "severity": "error",   "hint": "iam",          "http_status": 401},
    # Misc
    "RepositoryNotFoundException":         {"retriable": False, "severity": "error",   "hint": "missing",      "http_status": 404},
    "ImageNotFoundException":              {"retriable": False, "severity": "error",   "hint": "missing",      "http_status": 404},
    "RepositoryAlreadyExistsException":    {"retriable": False, "severity": "warning", "hint": "duplicate",    "http_status": 409},
    "ParameterNotFound":                   {"retriable": False, "severity": "error",   "hint": "missing",      "http_status": 400},
    "ParameterAlreadyExists":              {"retriable": False, "severity": "warning", "hint": "duplicate",    "http_status": 400},
    "InvalidDocument":                     {"retriable": False, "severity": "error",   "hint": "validation",   "http_status": 400},
    "TooManyUpdates":                      {"retriable": True,  "severity": "warning", "hint": "throttle",     "http_status": 429},
    "DBInstanceNotFound":                  {"retriable": False, "severity": "error",   "hint": "missing",      "http_status": 404},
    "DBClusterNotFoundFault":              {"retriable": False, "severity": "error",   "hint": "missing",      "http_status": 404},
    "DBInstanceAlreadyExists":             {"retriable": False, "severity": "warning", "hint": "duplicate",    "http_status": 409},
    "InsufficientDBInstanceCapacity":      {"retriable": True,  "severity": "warning", "hint": "capacity",     "http_status": 503},
    "InvalidDBClusterStateFault":          {"retriable": False, "severity": "error",   "hint": "state",        "http_status": 400},
    "StorageQuotaExceeded":                {"retriable": False, "severity": "error",   "hint": "quota",        "http_status": 400},
    "ClusterNotFoundException":            {"retriable": False, "severity": "error",   "hint": "missing",      "http_status": 404},
    "ServiceNotFoundException":            {"retriable": False, "severity": "error",   "hint": "missing",      "http_status": 404},
    "TaskNotFoundException":               {"retriable": False, "severity": "error",   "hint": "missing",      "http_status": 404},
    "AlreadyExists":                       {"retriable": False, "severity": "warning", "hint": "duplicate",    "http_status": 409},
    "ScalingActivityInProgress":           {"retriable": True,  "severity": "warning", "hint": "state",        "http_status": 400},
    "ResourceInUse":                       {"retriable": False, "severity": "warning", "hint": "dependency",   "http_status": 409},
    "ResourceLimitExceeded":               {"retriable": False, "severity": "error",   "hint": "quota",        "http_status": 400},
    "ResourceNotFound":                    {"retriable": False, "severity": "error",   "hint": "missing",      "http_status": 404},
    "AlarmNotFound":                       {"retriable": False, "severity": "error",   "hint": "missing",      "http_status": 404},
    "InvalidRequestException":             {"retriable": False, "severity": "error",   "hint": "validation",   "http_status": 400},
    "InvalidRequest":                      {"retriable": False, "severity": "error",   "hint": "validation",   "http_status": 400},
    "InvalidArgumentException":            {"retriable": False, "severity": "error",   "hint": "validation",   "http_status": 400},
    "BadRequestException":                 {"retriable": False, "severity": "error",   "hint": "validation",   "http_status": 400},
    "InvalidEventPatternException":        {"retriable": False, "severity": "error",   "hint": "validation",   "http_status": 400},
    "ManagedRuleException":                {"retriable": False, "severity": "warning", "hint": "iam",          "http_status": 400},
    "ModelTimeoutException":               {"retriable": True,  "severity": "warning", "hint": "timeout",      "http_status": 408},
    "ImageTooLargeException":              {"retriable": False, "severity": "error",   "hint": "validation",   "http_status": 400},
    "TextSizeLimitExceededException":      {"retriable": False, "severity": "error",   "hint": "validation",   "http_status": 400},
    "EntityNotFoundException":             {"retriable": False, "severity": "error",   "hint": "missing",      "http_status": 404},
    "EntityNotExistsException":            {"retriable": False, "severity": "error",   "hint": "missing",      "http_status": 404},
    "ConcurrentModificationException":     {"retriable": True,  "severity": "warning", "hint": "conflict",     "http_status": 409},
    "ConcurrentRunsExceededException":     {"retriable": False, "severity": "warning", "hint": "quota",        "http_status": 400},
    "ResourceNumberLimitExceededException": {"retriable": False, "severity": "error",  "hint": "quota",        "http_status": 400},
    "RuleLimitExceededException":          {"retriable": False, "severity": "error",   "hint": "quota",        "http_status": 400},
    "PipelineNotFoundException":           {"retriable": False, "severity": "error",   "hint": "missing",      "http_status": 404},
    "StageNotFoundException":              {"retriable": False, "severity": "error",   "hint": "missing",      "http_status": 404},
    "ApplicationDoesNotExistException":    {"retriable": False, "severity": "error",   "hint": "missing",      "http_status": 404},
    "DeploymentDoesNotExistException":     {"retriable": False, "severity": "error",   "hint": "missing",      "http_status": 404},
    "RepositoryDoesNotExistException":     {"retriable": False, "severity": "error",   "hint": "missing",      "http_status": 404},
    "BranchDoesNotExistException":         {"retriable": False, "severity": "error",   "hint": "missing",      "http_status": 404},
    "MessageRejected":                     {"retriable": False, "severity": "error",   "hint": "validation",   "http_status": 400},
    "MailFromDomainNotVerified":           {"retriable": False, "severity": "error",   "hint": "validation",   "http_status": 400},
    "ConfigurationSetDoesNotExistException": {"retriable": False, "severity": "error", "hint": "missing",     "http_status": 404},
    "ForbiddenException":                  {"retriable": False, "severity": "error",   "hint": "iam",          "http_status": 403},
    "FleetCapacityExceededException":      {"retriable": True,  "severity": "warning", "hint": "capacity",     "http_status": 503},
    "ContainerNotFoundException":          {"retriable": False, "severity": "error",   "hint": "missing",      "http_status": 404},
    "UnprocessableEntityException":        {"retriable": False, "severity": "error",   "hint": "validation",   "http_status": 422},
    "InvalidJobIdException":               {"retriable": False, "severity": "error",   "hint": "missing",      "http_status": 400},
    "DataUnavailableException":            {"retriable": False, "severity": "warning", "hint": "missing",      "http_status": 404},
    "DescribeChimeWebhookConfigurationsException": {"retriable": False, "severity": "error", "hint": "service", "http_status": 400},
    "OperationFailureException":           {"retriable": False, "severity": "error",   "hint": "service",      "http_status": 500},
    "OperationNotPermittedException":      {"retriable": False, "severity": "error",   "hint": "iam",          "http_status": 403},
    "RejectedRecordsException":            {"retriable": False, "severity": "warning", "hint": "validation",   "http_status": 400},
    "TooManyEnvironmentsException":        {"retriable": False, "severity": "error",   "hint": "quota",        "http_status": 400},
    "InvalidApplicationConfigurationException": {"retriable": False, "severity": "error", "hint": "validation","http_status": 400},
    "InvalidPaginationToken":              {"retriable": False, "severity": "warning", "hint": "validation",   "http_status": 400},
    "InvalidPaginationTokenException":     {"retriable": False, "severity": "warning", "hint": "validation",   "http_status": 400},
    "ResourceShareLimitExceededException": {"retriable": False, "severity": "error",   "hint": "quota",        "http_status": 400},
    "UnknownResourceException":            {"retriable": False, "severity": "error",   "hint": "missing",      "http_status": 404},
    "ClusterNotFound":                     {"retriable": False, "severity": "error",   "hint": "missing",      "http_status": 404},
    "InvalidClusterState":                 {"retriable": False, "severity": "error",   "hint": "state",        "http_status": 400},
    "InsufficientClusterCapacity":         {"retriable": True,  "severity": "warning", "hint": "capacity",     "http_status": 503},
    "NoUpdateAvailableException":          {"retriable": False, "severity": "warning", "hint": "state",        "http_status": 400},
    "ChangeSetNotFound":                   {"retriable": False, "severity": "error",   "hint": "missing",      "http_status": 404},
    "InsufficientCapabilitiesException":   {"retriable": False, "severity": "error",   "hint": "iam",          "http_status": 400},
    "StackInstanceNotFoundException":      {"retriable": False, "severity": "error",   "hint": "missing",      "http_status": 404},
    "AlreadyExistsException":              {"retriable": False, "severity": "warning", "hint": "duplicate",    "http_status": 409},
    "PipelineNotFoundException":           {"retriable": False, "severity": "error",   "hint": "missing",      "http_status": 404},
    "FleetNotFoundException":              {"retriable": False, "severity": "error",   "hint": "missing",      "http_status": 404},
    "FilterPolicyLimitExceededException":  {"retriable": False, "severity": "error",   "hint": "quota",        "http_status": 400},
    "AuthorizationErrorException":         {"retriable": False, "severity": "error",   "hint": "iam",          "http_status": 403},
    "ThrottledException":                  {"retriable": True,  "severity": "warning", "hint": "throttle",     "http_status": 429},
    "InternalException":                   {"retriable": True,  "severity": "error",   "hint": "service",      "http_status": 500},
    "BaseException":                       {"retriable": False, "severity": "error",   "hint": "service",      "http_status": 500},
    "ClientLimitExceededException":        {"retriable": True,  "severity": "warning", "hint": "throttle",     "http_status": 429},
    "DisabledOperationException":          {"retriable": False, "severity": "warning", "hint": "state",        "http_status": 400},
    "DirectoryNotShared":                  {"retriable": False, "severity": "warning", "hint": "state",        "http_status": 400},
    "RequestInProgressException":          {"retriable": True,  "severity": "warning", "hint": "state",        "http_status": 409},
    "WAFNonexistentItemException":         {"retriable": False, "severity": "error",   "hint": "missing",      "http_status": 404},
    "WAFLimitsExceededException":          {"retriable": False, "severity": "error",   "hint": "quota",        "http_status": 400},
    "BadRequestException":                 {"retriable": False, "severity": "error",   "hint": "validation",   "http_status": 400},
    "DirectConnectClientException":        {"retriable": False, "severity": "error",   "hint": "validation",   "http_status": 400},
    "DirectConnectServerException":        {"retriable": True,  "severity": "error",   "hint": "service",      "http_status": 500},
    "PipelineNotFoundException":           {"retriable": False, "severity": "error",   "hint": "missing",      "http_status": 404},
    "AlreadyExistsException":              {"retriable": False, "severity": "warning", "hint": "duplicate",    "http_status": 409},
    "UnauthorizedException":               {"retriable": False, "severity": "error",   "hint": "iam",          "http_status": 401},
    "TaskStoppedException":                {"retriable": False, "severity": "warning", "hint": "state",        "http_status": 400},
    "ClientException":                     {"retriable": False, "severity": "error",   "hint": "validation",   "http_status": 400},
    "ServerException":                     {"retriable": True,  "severity": "error",   "hint": "service",      "http_status": 500},
    "InvalidGatewayRequestException":      {"retriable": False, "severity": "error",   "hint": "validation",   "http_status": 400},
    "FileSystemNotFound":                  {"retriable": False, "severity": "error",   "hint": "missing",      "http_status": 404},
    "MountTargetNotFound":                 {"retriable": False, "severity": "error",   "hint": "missing",      "http_status": 404},
    "ThroughputLimitExceeded":             {"retriable": False, "severity": "error",   "hint": "quota",        "http_status": 400},
    "BackupNotFound":                      {"retriable": False, "severity": "error",   "hint": "missing",      "http_status": 404},
    "TrailNotFoundException":              {"retriable": False, "severity": "error",   "hint": "missing",      "http_status": 404},
    "InsufficientS3BucketPolicyException": {"retriable": False, "severity": "error",   "hint": "policy",       "http_status": 400},
    "ResourceNotFoundFault":               {"retriable": False, "severity": "error",   "hint": "missing",      "http_status": 404},
    "InvalidResourceStateFault":           {"retriable": False, "severity": "warning", "hint": "state",        "http_status": 400},
    "NoSuchHostedZone":                    {"retriable": False, "severity": "error",   "hint": "missing",      "http_status": 404},
    "NoSuchHealthCheck":                   {"retriable": False, "severity": "error",   "hint": "missing",      "http_status": 404},
    "HostedZoneAlreadyExists":             {"retriable": False, "severity": "warning", "hint": "duplicate",    "http_status": 409},
    "NoSuchDistribution":                  {"retriable": False, "severity": "error",   "hint": "missing",      "http_status": 404},
    "DistributionNotDisabled":             {"retriable": False, "severity": "warning", "hint": "state",        "http_status": 409},
    "TooManyDistributions":                {"retriable": False, "severity": "error",   "hint": "quota",        "http_status": 400},
    "InvalidArgument":                     {"retriable": False, "severity": "error",   "hint": "validation",   "http_status": 400},
    "NotFoundException":                   {"retriable": False, "severity": "error",   "hint": "missing",      "http_status": 404},
    "ListenerNotFoundException":           {"retriable": False, "severity": "error",   "hint": "missing",      "http_status": 404},
    "AcceleratorNotFoundException":        {"retriable": False, "severity": "error",   "hint": "missing",      "http_status": 404},
    "NamespaceNotFound":                   {"retriable": False, "severity": "error",   "hint": "missing",      "http_status": 404},
    "ServiceNotFound":                     {"retriable": False, "severity": "error",   "hint": "missing",      "http_status": 404},
    "PipelineNotFoundException":           {"retriable": False, "severity": "error",   "hint": "missing",      "http_status": 404},
    "ServiceFailureException":             {"retriable": True,  "severity": "error",   "hint": "service",      "http_status": 500},
    "LexiconNotFoundException":            {"retriable": False, "severity": "error",   "hint": "missing",      "http_status": 404},
    "InvalidOperationException":           {"retriable": False, "severity": "error",   "hint": "validation",   "http_status": 400},
    "DuplicateResourceException":          {"retriable": False, "severity": "warning", "hint": "duplicate",    "http_status": 409},
    "BackupRequestStoppedException":       {"retriable": False, "severity": "warning", "hint": "state",        "http_status": 400},
    "CloudHsmResourceNotFoundException":   {"retriable": False, "severity": "error",   "hint": "missing",      "http_status": 404},
    "CloudHsmInternalFailureException":    {"retriable": True,  "severity": "error",   "hint": "service",      "http_status": 500},
    "InvalidAccessException":              {"retriable": False, "severity": "error",   "hint": "iam",          "http_status": 403},
    "PipelineNotFoundException":           {"retriable": False, "severity": "error",   "hint": "missing",      "http_status": 404},
    "DescribeDirectoryException":          {"retriable": False, "severity": "error",   "hint": "missing",      "http_status": 404},
    "AccountNotFoundException":            {"retriable": False, "severity": "error",   "hint": "missing",      "http_status": 404},
    "TaskFailedException":                 {"retriable": False, "severity": "error",   "hint": "state",        "http_status": 400},
    "FleetNotFoundException":              {"retriable": False, "severity": "error",   "hint": "missing",      "http_status": 404},
}


# ---------------------------------------------------------------------------
# Build & write
# ---------------------------------------------------------------------------

def build():
    OUT.mkdir(parents=True, exist_ok=True)
    if not SERVICES_MD.exists():
        raise SystemExit(f"missing {SERVICES_MD}")
    services: dict[str, dict] = {}
    for raw in SERVICES_MD.read_text(encoding="utf-8").splitlines():
        line = raw.strip().lstrip("*").strip()
        if not line:
            continue
        if line in DENYLIST:
            continue
        slug = _slug(line)
        ov = SLUG_OVERRIDES.get(line)
        if ov:
            _, category, resources, errs = ov
        else:
            category, resources, errs = "other", ["resources"], []
        # Idempotent: prefer richer record if duplicate slug
        if slug in services and ov is None:
            continue
        services[slug] = {
            "slug": slug,
            "name": line,
            "category": category,
            "resources": resources,
            "errors": list(set(errs + [
                "ResourceNotFoundException", "ThrottlingException",
                "AccessDeniedException"])),
        }

    # Build action catalog (cartesian product, then prune nonsensical combos).
    actions: list[dict] = []
    for slug, svc in services.items():
        for verb in GENERIC_VERBS:
            # Skip a few combos that don't exist for marketplace/billing-style
            # services — they're read-only catalogs.
            if svc["category"] in ("billing", "compliance", "marketplace") \
                    and verb["kind"] in ("write", "mutate"):
                continue
            action_id = f"{slug}.{verb['verb']}"
            errs = list(set(verb["default_errors"] + svc["errors"]))
            actions.append({
                "id": action_id,
                "service": slug,
                "verb": verb["verb"],
                "kind": verb["kind"],
                "category": svc["category"],
                "params": verb["params"],
                "may_fail_with": errs[:8],
            })

    # Errors catalog: union of generic + every per-service error.
    errors_out: dict[str, dict] = dict(ERROR_CATALOG)
    for svc in services.values():
        for code in svc["errors"]:
            if code not in errors_out:
                errors_out[code] = {"retriable": False, "severity": "error",
                                    "hint": "service", "http_status": 400}

    (OUT / "services.json").write_text(json.dumps(services, indent=2),
                                       encoding="utf-8")
    (OUT / "actions.json").write_text(json.dumps(actions, indent=2),
                                      encoding="utf-8")
    (OUT / "errors.json").write_text(json.dumps(errors_out, indent=2),
                                     encoding="utf-8")

    print(f"services: {len(services)}")
    print(f"actions:  {len(actions)}")
    print(f"errors:   {len(errors_out)}")


if __name__ == "__main__":
    build()
