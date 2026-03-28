package main

import (
	"context"
	"database/sql"
	"encoding/json"
	"fmt"
	"log"
	"net/http"
	"os"
	"strconv"
	"time"

	"github.com/gin-gonic/gin"
	_ "github.com/lib/pq"
	"github.com/prometheus/client_golang/prometheus"
	"github.com/prometheus/client_golang/prometheus/promhttp"
	"github.com/redis/go-redis/v9"
)

// --- Models ---

type Product struct {
	ProductID   string  `json:"product_id" db:"product_id"`
	Name        string  `json:"name" db:"name"`
	Description string  `json:"description" db:"description"`
	Price       float64 `json:"price" db:"price"`
	StockCount  int     `json:"stock_count" db:"stock_count"`
}

// --- Globals ---

var (
	db  *sql.DB
	rdb *redis.Client
	ctx = context.Background()

	httpRequestsTotal = prometheus.NewCounterVec(
		prometheus.CounterOpts{Name: "http_requests_total", Help: "Total HTTP requests"},
		[]string{"method", "endpoint", "status_code"},
	)
	httpRequestDuration = prometheus.NewHistogramVec(
		prometheus.HistogramOpts{Name: "http_request_duration_seconds", Help: "HTTP request duration"},
		[]string{"method", "endpoint"},
	)
	redisPoolSize = prometheus.NewGauge(
		prometheus.GaugeOpts{Name: "redis_connection_pool_size", Help: "Redis connection pool size"},
	)
	cacheHitsTotal   = prometheus.NewCounter(prometheus.CounterOpts{Name: "cache_hits_total", Help: "Cache hits"})
	cacheMissesTotal = prometheus.NewCounter(prometheus.CounterOpts{Name: "cache_misses_total", Help: "Cache misses"})
)

func init() {
	prometheus.MustRegister(httpRequestsTotal, httpRequestDuration, redisPoolSize, cacheHitsTotal, cacheMissesTotal)
}

func getEnv(key, fallback string) string {
	if v := os.Getenv(key); v != "" {
		return v
	}
	return fallback
}

func main() {
	// Database
	dbURL := getEnv("DATABASE_URL", "postgres://postgres:password@localhost:5432/acmecorp?sslmode=disable")
	var err error
	db, err = sql.Open("postgres", dbURL)
	if err != nil {
		log.Fatalf("Failed to connect to database: %v", err)
	}
	defer db.Close()

	if err := createProductsTable(); err != nil {
		log.Printf("Warning: could not create products table: %v", err)
	}

	// Redis
	poolSize, _ := strconv.Atoi(getEnv("REDIS_POOL_SIZE", "10"))
	rdb = redis.NewClient(&redis.Options{
		Addr:     getEnv("REDIS_ADDR", "localhost:6379"),
		PoolSize: poolSize,
	})
	redisPoolSize.Set(float64(poolSize))

	// Seed products
	seedProducts()

	// Router
	gin.SetMode(gin.ReleaseMode)
	r := gin.New()
	r.Use(gin.Recovery(), metricsMiddleware())

	r.GET("/products", getProducts)
	r.GET("/products/:id", getProduct)
	r.POST("/products/:id/reserve", reserveStock)
	r.GET("/health", healthCheck)
	r.GET("/metrics", gin.WrapH(promhttp.Handler()))

	port := getEnv("PORT", "4002")
	log.Printf("inventory-service starting on :%s", port)
	if err := r.Run(":" + port); err != nil {
		log.Fatalf("Server failed: %v", err)
	}
}

func metricsMiddleware() gin.HandlerFunc {
	return func(c *gin.Context) {
		start := time.Now()
		c.Next()
		duration := time.Since(start).Seconds()
		httpRequestsTotal.WithLabelValues(c.Request.Method, c.FullPath(), strconv.Itoa(c.Writer.Status())).Inc()
		httpRequestDuration.WithLabelValues(c.Request.Method, c.FullPath()).Observe(duration)
	}
}

func createProductsTable() error {
	_, err := db.Exec(`
		CREATE TABLE IF NOT EXISTS products (
			product_id VARCHAR(100) PRIMARY KEY,
			name VARCHAR(255) NOT NULL,
			description TEXT,
			price NUMERIC(12,4) NOT NULL,
			stock_count INTEGER NOT NULL DEFAULT 0
		)
	`)
	return err
}

func seedProducts() {
	var count int
	err := db.QueryRow("SELECT COUNT(*) FROM products").Scan(&count)
	if err != nil || count > 0 {
		return
	}

	products := []Product{
		{"PROD-001", "Premium Wireless Headphones", "Noise-cancelling over-ear headphones with 30hr battery", 249.99, 50},
		{"PROD-002", "Mechanical Keyboard", "Cherry MX Brown switches, RGB backlit, full-size", 159.99, 75},
		{"PROD-003", "4K Ultra Monitor", "32-inch IPS display, 144Hz, HDR600", 599.99, 25},
		{"PROD-004", "Ergonomic Mouse", "Vertical design, wireless, 6 programmable buttons", 79.99, 100},
		{"PROD-005", "USB-C Hub Pro", "12-in-1: HDMI, ethernet, SD card, 100W PD", 89.99, 120},
		{"PROD-006", "Standing Desk Mat", "Anti-fatigue, beveled edges, 20x36 inches", 49.99, 200},
		{"PROD-007", "Webcam 4K", "Auto-focus, built-in ring light, privacy shutter", 129.99, 60},
		{"PROD-008", "Laptop Stand", "Aluminum, adjustable height, foldable", 44.99, 150},
		{"PROD-009", "Cable Management Kit", "100 pieces: ties, clips, sleeves, labels", 24.99, 300},
		{"PROD-010", "Desk Organizer", "Bamboo, 5 compartments, phone holder", 34.99, 180},
		{"PROD-011", "Blue Light Glasses", "Computer glasses, anti-glare, lightweight frame", 39.99, 250},
		{"PROD-012", "Wireless Charger Pad", "15W fast charging, Qi compatible, LED indicator", 29.99, 200},
		{"PROD-013", "Portable SSD 1TB", "USB 3.2 Gen 2, 1050MB/s read, shock resistant", 119.99, 80},
		{"PROD-014", "Smart Power Strip", "4 outlets, 4 USB ports, voice control compatible", 34.99, 150},
		{"PROD-015", "Noise Machine", "20 soothing sounds, timer, portable", 39.99, 90},
		{"PROD-016", "Desk Lamp LED", "Eye-care, 5 color modes, USB charging port", 54.99, 110},
		{"PROD-017", "Wrist Rest Keyboard", "Memory foam, cooling gel, non-slip base", 19.99, 280},
		{"PROD-018", "Screen Cleaner Kit", "Microfiber cloth, spray solution, brush", 14.99, 350},
		{"PROD-019", "Thunderbolt 4 Cable", "0.8m, 40Gbps, 100W PD, Intel certified", 39.99, 160},
		{"PROD-020", "Desk Shelf Monitor Riser", "Bamboo, drawer storage, cable management", 64.99, 70},
	}

	for _, p := range products {
		_, err := db.Exec(
			"INSERT INTO products (product_id, name, description, price, stock_count) VALUES ($1, $2, $3, $4, $5) ON CONFLICT DO NOTHING",
			p.ProductID, p.Name, p.Description, p.Price, p.StockCount,
		)
		if err != nil {
			log.Printf("Failed to seed product %s: %v", p.ProductID, err)
		}
		// Also cache in Redis
		data, _ := json.Marshal(p)
		rdb.Set(ctx, "product:"+p.ProductID, data, 0)
	}

	log.Println("Seeded 20 products")
}

func getProducts(c *gin.Context) {
	// Try Redis first
	keys, err := rdb.Keys(ctx, "product:*").Result()
	if err == nil && len(keys) > 0 {
		cacheHitsTotal.Inc()
		products := make([]Product, 0, len(keys))
		for _, key := range keys {
			data, err := rdb.Get(ctx, key).Result()
			if err != nil {
				continue
			}
			var p Product
			if json.Unmarshal([]byte(data), &p) == nil {
				products = append(products, p)
			}
		}
		if len(products) > 0 {
			c.JSON(http.StatusOK, products)
			return
		}
	}

	cacheMissesTotal.Inc()

	// Fallback to Postgres
	rows, err := db.Query("SELECT product_id, name, description, price, stock_count FROM products")
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": "Database query failed"})
		return
	}
	defer rows.Close()

	var products []Product
	for rows.Next() {
		var p Product
		if err := rows.Scan(&p.ProductID, &p.Name, &p.Description, &p.Price, &p.StockCount); err != nil {
			continue
		}
		products = append(products, p)
	}
	c.JSON(http.StatusOK, products)
}

func getProduct(c *gin.Context) {
	id := c.Param("id")

	// Try Redis
	data, err := rdb.Get(ctx, "product:"+id).Result()
	if err == nil {
		cacheHitsTotal.Inc()
		var p Product
		if json.Unmarshal([]byte(data), &p) == nil {
			c.JSON(http.StatusOK, p)
			return
		}
	}

	cacheMissesTotal.Inc()

	// Fallback to Postgres
	var p Product
	err = db.QueryRow(
		"SELECT product_id, name, description, price, stock_count FROM products WHERE product_id = $1",
		id,
	).Scan(&p.ProductID, &p.Name, &p.Description, &p.Price, &p.StockCount)
	if err != nil {
		c.JSON(http.StatusNotFound, gin.H{"error": "Product not found"})
		return
	}
	c.JSON(http.StatusOK, p)
}

type ReserveRequest struct {
	Quantity int `json:"quantity"`
}

func reserveStock(c *gin.Context) {
	id := c.Param("id")
	var req ReserveRequest
	if err := c.ShouldBindJSON(&req); err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": "Invalid request"})
		return
	}
	if req.Quantity <= 0 {
		c.JSON(http.StatusBadRequest, gin.H{"error": "Quantity must be positive"})
		return
	}

	// Atomic decrement in Redis
	remaining, err := rdb.DecrBy(ctx, fmt.Sprintf("stock:%s", id), int64(req.Quantity)).Result()
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": "Redis operation failed"})
		return
	}

	if remaining < 0 {
		// Rollback
		rdb.IncrBy(ctx, fmt.Sprintf("stock:%s", id), int64(req.Quantity))
		c.JSON(http.StatusConflict, gin.H{"success": false, "error": "Insufficient stock"})
		return
	}

	c.JSON(http.StatusOK, gin.H{"success": true, "remaining_stock": remaining})
}

func healthCheck(c *gin.Context) {
	redisOK := "ok"
	if err := rdb.Ping(ctx).Err(); err != nil {
		redisOK = "error"
	}

	dbOK := "ok"
	if err := db.Ping(); err != nil {
		dbOK = "error"
	}

	status := "ok"
	if redisOK == "error" || dbOK == "error" {
		status = "degraded"
	}

	c.JSON(http.StatusOK, gin.H{
		"status": status,
		"redis":  redisOK,
		"db":     dbOK,
	})
}
