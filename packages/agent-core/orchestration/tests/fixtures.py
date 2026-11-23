"""A tiny Android project used across tests."""

MANIFEST = b"""<?xml version="1.0" encoding="utf-8"?>
<manifest xmlns:android="http://schemas.android.com/apk/res/android">
    <uses-permission android:name="android.permission.INTERNET"/>
    <application android:name=".App">
        <activity android:name=".LoginActivity" android:exported="true">
            <intent-filter>
                <action android:name="android.intent.action.MAIN"/>
                <category android:name="android.intent.category.LAUNCHER"/>
            </intent-filter>
        </activity>
    </application>
</manifest>"""

GRADLE = b"""plugins { id("com.android.application"); id("org.jetbrains.kotlin.android") }
android {
    namespace = "com.example.shop"
    compileSdk = 35
    defaultConfig { applicationId = "com.example.shop"; minSdk = 24; targetSdk = 35 }
}
dependencies {
    implementation("com.squareup.retrofit2:retrofit:2.11.0")
    implementation("androidx.room:room-runtime:2.6.1")
    implementation("com.google.firebase:firebase-auth:23.0.0")
}
"""

AUTH_REPO = b"""package com.example.shop.auth

import com.google.firebase.auth.FirebaseAuth

class AuthRepository(private val auth: FirebaseAuth) {
    suspend fun loginWithEmail(email: String, password: String): Boolean = true
    fun logout() {}
}
"""

LOGIN_ACTIVITY = b"""package com.example.shop

import androidx.appcompat.app.AppCompatActivity
import com.example.shop.auth.AuthRepository

class LoginActivity : AppCompatActivity() {
    private lateinit var repo: AuthRepository
    fun onLoginClicked() { }
}
"""

API = b"""package com.example.shop.net

import retrofit2.http.GET
import retrofit2.http.POST

interface ShopApi {
    @GET("products")
    suspend fun listProducts(): List<String>
    @POST("orders")
    suspend fun createOrder(): String
}
"""

SECRETS = b"""sdk.dir=C:\\\\Android\\nstorePassword=hunter2hunter2\\n"""

FILES: dict[str, bytes] = {
    "app/src/main/AndroidManifest.xml": MANIFEST,
    "app/build.gradle.kts": GRADLE,
    "app/src/main/java/com/example/shop/auth/AuthRepository.kt": AUTH_REPO,
    "app/src/main/java/com/example/shop/LoginActivity.kt": LOGIN_ACTIVITY,
    "app/src/main/java/com/example/shop/net/ShopApi.kt": API,
    "local.properties": SECRETS,
    "app/build/generated/Junk.kt": b"class Junk",
    "../escape.kt": b"class Escape",
}
