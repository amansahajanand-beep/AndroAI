"""Curated names the analyser recognises: annotations, framework base classes, libraries.

These tables are data. A name is only ever *looked up* here; nothing is fetched or executed. A
library that is not listed is simply not recognised (it is never reported as absent).
"""

from __future__ import annotations

from collections.abc import Iterable


def _both(package_old: str, package_new: str, names: Iterable[str]) -> dict[str, tuple[str, ...]]:
    return {n: (f"{package_new}.{n}", f"{package_old}.{n}") for n in names}


_ROOM_NAMES = (
    "Database Entity Dao Query Insert Update Delete Upsert RawQuery Transaction PrimaryKey "
    "ColumnInfo Embedded Relation ForeignKey Index TypeConverters TypeConverter Ignore Fts4 "
    "DatabaseView AutoMigration Junction"
).split()
_RETROFIT_NAMES = (
    "GET POST PUT DELETE PATCH HEAD OPTIONS HTTP Headers Header Path Query QueryMap Body Field "
    "FieldMap FormUrlEncoded Multipart Part PartMap Streaming Url"
).split()

KNOWN_ANNOTATIONS: dict[str, tuple[str, ...]] = {
    **_both("android.arch.persistence.room", "androidx.room", _ROOM_NAMES),
    **{n: (f"retrofit2.http.{n}",) for n in _RETROFIT_NAMES},
    "Composable": ("androidx.compose.runtime.Composable",),
    "Preview": (
        "androidx.compose.ui.tooling.preview.Preview",
        "androidx.compose.desktop.ui.tooling.preview.Preview",
    ),
    "HiltAndroidApp": ("dagger.hilt.android.HiltAndroidApp",),
    "AndroidEntryPoint": ("dagger.hilt.android.AndroidEntryPoint",),
    "HiltViewModel": ("dagger.hilt.android.lifecycle.HiltViewModel",),
    "HiltWorker": ("androidx.hilt.work.HiltWorker",),
    "InstallIn": ("dagger.hilt.InstallIn",),
    "EntryPoint": ("dagger.hilt.EntryPoint",),
    "TestInstallIn": ("dagger.hilt.testing.TestInstallIn",),
    "Module": ("dagger.Module", "org.koin.core.annotation.Module"),
    "Provides": ("dagger.Provides",),
    "Binds": ("dagger.Binds",),
    "BindsInstance": ("dagger.BindsInstance",),
    "Component": ("dagger.Component",),
    "Subcomponent": ("dagger.Subcomponent",),
    "Reusable": ("dagger.Reusable",),
    "IntoSet": ("dagger.multibindings.IntoSet",),
    "IntoMap": ("dagger.multibindings.IntoMap",),
    "AssistedInject": ("dagger.assisted.AssistedInject",),
    "AssistedFactory": ("dagger.assisted.AssistedFactory",),
    "Assisted": ("dagger.assisted.Assisted",),
    "Inject": ("javax.inject.Inject", "jakarta.inject.Inject"),
    "Singleton": ("javax.inject.Singleton", "jakarta.inject.Singleton"),
    "Named": ("javax.inject.Named", "jakarta.inject.Named", "org.koin.core.annotation.Named"),
    "Qualifier": ("javax.inject.Qualifier", "jakarta.inject.Qualifier"),
    "Scope": ("javax.inject.Scope", "jakarta.inject.Scope"),
    "ActivityScoped": ("dagger.hilt.android.scopes.ActivityScoped",),
    "FragmentScoped": ("dagger.hilt.android.scopes.FragmentScoped",),
    "ViewModelScoped": ("dagger.hilt.android.scopes.ViewModelScoped",),
    "ActivityRetainedScoped": ("dagger.hilt.android.scopes.ActivityRetainedScoped",),
    "ApplicationContext": ("dagger.hilt.android.qualifiers.ApplicationContext",),
    "ActivityContext": ("dagger.hilt.android.qualifiers.ActivityContext",),
    "KoinViewModel": ("org.koin.android.annotation.KoinViewModel",),
    "Single": ("org.koin.core.annotation.Single",),
    "Factory": ("org.koin.core.annotation.Factory",),
    "ComponentScan": ("org.koin.core.annotation.ComponentScan",),
    "Serializable": ("kotlinx.serialization.Serializable",),
    "Parcelize": ("kotlinx.parcelize.Parcelize", "kotlinx.android.parcel.Parcelize"),
    "SerializedName": ("com.google.gson.annotations.SerializedName",),
    "JsonClass": ("com.squareup.moshi.JsonClass",),
}


# ``Query`` exists in both libraries; the later dict entry above would otherwise hide Room's.
KNOWN_ANNOTATIONS["Query"] = (
    "androidx.room.Query",
    "android.arch.persistence.room.Query",
    "retrofit2.http.Query",
)


def accepted(name: str) -> tuple[str, ...]:
    """The fully qualified names an annotation called ``name`` may stand for."""
    return KNOWN_ANNOTATIONS.get(name, ())


# Framework base classes by the role they give a class: role -> simple name -> accepted FQNs.
ROLE_BASES: dict[str, dict[str, tuple[str, ...]]] = {
    "activity": {
        "Activity": ("android.app.Activity",),
        "ComponentActivity": ("androidx.activity.ComponentActivity",),
        "AppCompatActivity": ("androidx.appcompat.app.AppCompatActivity",),
        "FragmentActivity": ("androidx.fragment.app.FragmentActivity",),
        "ListActivity": ("android.app.ListActivity",),
        "PreferenceActivity": ("android.preference.PreferenceActivity",),
        "NativeActivity": ("android.app.NativeActivity",),
    },
    "fragment": {
        "Fragment": ("androidx.fragment.app.Fragment", "android.app.Fragment"),
        "DialogFragment": ("androidx.fragment.app.DialogFragment", "android.app.DialogFragment"),
        "ListFragment": ("androidx.fragment.app.ListFragment", "android.app.ListFragment"),
        "BottomSheetDialogFragment": (
            "com.google.android.material.bottomsheet.BottomSheetDialogFragment",
        ),
        "PreferenceFragmentCompat": ("androidx.preference.PreferenceFragmentCompat",),
    },
    "viewmodel": {
        "ViewModel": ("androidx.lifecycle.ViewModel",),
        "AndroidViewModel": ("androidx.lifecycle.AndroidViewModel",),
    },
    "service": {
        "Service": ("android.app.Service",),
        "LifecycleService": ("androidx.lifecycle.LifecycleService",),
        "JobIntentService": ("androidx.core.app.JobIntentService",),
        "IntentService": ("android.app.IntentService",),
        "JobService": ("android.app.job.JobService",),
        "FirebaseMessagingService": ("com.google.firebase.messaging.FirebaseMessagingService",),
        "MediaSessionService": ("androidx.media3.session.MediaSessionService",),
        "VpnService": ("android.net.VpnService",),
        "AccessibilityService": ("android.accessibilityservice.AccessibilityService",),
    },
    "receiver": {
        "BroadcastReceiver": ("android.content.BroadcastReceiver",),
        "AppWidgetProvider": ("android.appwidget.AppWidgetProvider",),
    },
    "provider": {"ContentProvider": ("android.content.ContentProvider",)},
    "application": {
        "Application": ("android.app.Application",),
        "MultiDexApplication": ("androidx.multidex.MultiDexApplication",),
    },
    "worker": {
        "Worker": ("androidx.work.Worker",),
        "CoroutineWorker": ("androidx.work.CoroutineWorker",),
        "ListenableWorker": ("androidx.work.ListenableWorker",),
        "RxWorker": ("androidx.work.RxWorker",),
    },
    "adapter": {
        "RecyclerView.Adapter": ("androidx.recyclerview.widget.RecyclerView.Adapter",),
        "ListAdapter": ("androidx.recyclerview.widget.ListAdapter",),
        "PagingDataAdapter": ("androidx.paging.PagingDataAdapter",),
    },
    "custom_view": {
        "View": ("android.view.View",),
        "FrameLayout": ("android.widget.FrameLayout",),
        "LinearLayout": ("android.widget.LinearLayout",),
        "RelativeLayout": ("android.widget.RelativeLayout",),
        "ConstraintLayout": ("androidx.constraintlayout.widget.ConstraintLayout",),
        "AppCompatTextView": ("androidx.appcompat.widget.AppCompatTextView",),
        "AppCompatImageView": ("androidx.appcompat.widget.AppCompatImageView",),
    },
    "paging_source": {"PagingSource": ("androidx.paging.PagingSource",)},
    "room_database": {"RoomDatabase": ("androidx.room.RoomDatabase",)},
    "sqlite_helper": {"SQLiteOpenHelper": ("android.database.sqlite.SQLiteOpenHelper",)},
    "http_interceptor": {"Interceptor": ("okhttp3.Interceptor",)},
}

# Roles that become facts of their own kind. (room_database, sqlite_helper and http_interceptor
# are reported by the data extractor, which knows more about them.)
ROLE_FACT_KINDS = (
    "activity",
    "fragment",
    "viewmodel",
    "service",
    "receiver",
    "provider",
    "application",
    "worker",
    "adapter",
    "custom_view",
    "paging_source",
)

# Libraries by Maven coordinate prefix ("group:artifact"): (prefix, technology, category).
# The longest matching prefix wins.
COORDINATE_TECH: tuple[tuple[str, str, str], ...] = (
    ("androidx.compose", "compose", "ui"),
    ("androidx.activity:activity-compose", "compose", "ui"),
    ("androidx.navigation:navigation-compose", "navigation_compose", "navigation"),
    ("androidx.navigation:navigation-fragment", "navigation_fragment", "navigation"),
    ("androidx.navigation:navigation-ui", "navigation_fragment", "navigation"),
    ("androidx.navigation:navigation-runtime", "navigation", "navigation"),
    ("androidx.navigation:navigation-common", "navigation", "navigation"),
    ("androidx.navigation3", "navigation3", "navigation"),
    ("androidx.appcompat:", "appcompat", "ui"),
    ("com.google.android.material:", "material_components", "ui"),
    ("androidx.recyclerview:", "recyclerview", "ui"),
    ("androidx.constraintlayout:constraintlayout-compose", "compose", "ui"),
    ("androidx.constraintlayout:", "constraintlayout", "ui"),
    ("androidx.fragment:", "fragment", "ui"),
    ("androidx.viewpager2:", "viewpager2", "ui"),
    ("androidx.room:", "room", "storage"),
    ("android.arch.persistence.room", "room", "storage"),
    ("androidx.datastore:", "datastore", "storage"),
    ("androidx.preference:", "preferences", "storage"),
    ("androidx.security:security-crypto", "encrypted_storage", "storage"),
    ("io.realm", "realm", "storage"),
    ("io.objectbox", "objectbox", "storage"),
    ("app.cash.sqldelight", "sqldelight", "storage"),
    ("com.google.firebase:firebase-firestore", "firestore", "storage"),
    ("com.google.firebase:firebase-database", "firebase_realtime_database", "storage"),
    ("com.squareup.retrofit2:retrofit", "retrofit", "network"),
    ("com.squareup.retrofit2:converter-", "retrofit_converter", "network"),
    ("com.squareup.retrofit2:adapter-", "retrofit_adapter", "network"),
    ("com.squareup.okhttp3:", "okhttp", "network"),
    ("io.ktor:ktor-client", "ktor_client", "network"),
    ("com.android.volley:", "volley", "network"),
    ("com.apollographql", "apollo_graphql", "network"),
    ("com.github.kittinunf.fuel", "fuel", "network"),
    ("com.google.code.gson:", "gson", "serialization"),
    ("com.squareup.moshi:", "moshi", "serialization"),
    ("org.jetbrains.kotlinx:kotlinx-serialization", "kotlinx_serialization", "serialization"),
    ("com.fasterxml.jackson", "jackson", "serialization"),
    ("com.google.dagger:hilt", "hilt", "di"),
    ("androidx.hilt:", "hilt", "di"),
    ("com.google.dagger:dagger", "dagger", "di"),
    ("io.insert-koin:", "koin", "di"),
    ("org.kodein.di", "kodein", "di"),
    ("me.tatarka.inject", "kotlin_inject", "di"),
    ("androidx.lifecycle:lifecycle-viewmodel", "viewmodel", "architecture"),
    ("androidx.lifecycle:lifecycle-livedata", "livedata", "architecture"),
    ("androidx.lifecycle:lifecycle-runtime", "lifecycle", "architecture"),
    ("androidx.work:", "workmanager", "architecture"),
    ("androidx.paging:", "paging", "architecture"),
    ("org.jetbrains.kotlinx:kotlinx-coroutines", "coroutines", "async"),
    ("io.reactivex", "rxjava", "async"),
    ("io.coil-kt", "coil", "image"),
    ("com.github.bumptech.glide", "glide", "image"),
    ("com.squareup.picasso", "picasso", "image"),
    ("com.google.firebase:firebase-auth", "firebase_auth", "firebase"),
    ("com.google.firebase:firebase-messaging", "firebase_messaging", "firebase"),
    ("com.google.firebase:firebase-crashlytics", "crashlytics", "firebase"),
    ("com.google.firebase:firebase-analytics", "firebase_analytics", "firebase"),
    ("com.google.firebase:", "firebase", "firebase"),
    ("junit:junit", "junit", "testing"),
    ("org.junit", "junit", "testing"),
    ("androidx.test", "androidx_test", "testing"),
    ("io.mockk", "mockk", "testing"),
    ("org.mockito", "mockito", "testing"),
    ("com.google.truth", "truth", "testing"),
    ("org.robolectric", "robolectric", "testing"),
    ("app.cash.turbine", "turbine", "testing"),
)

# Gradle plugin ids -> (technology, category).
PLUGIN_TECH: dict[str, tuple[str, str]] = {
    "com.google.dagger.hilt.android": ("hilt", "di"),
    "dagger.hilt.android.plugin": ("hilt", "di"),
    "com.google.devtools.ksp": ("ksp", "build"),
    "org.jetbrains.kotlin.kapt": ("kapt", "build"),
    "kotlin-kapt": ("kapt", "build"),
    "androidx.room": ("room", "storage"),
    "org.jetbrains.kotlin.plugin.compose": ("compose", "ui"),
    "org.jetbrains.kotlin.plugin.serialization": ("kotlinx_serialization", "serialization"),
    "kotlinx-serialization": ("kotlinx_serialization", "serialization"),
    "org.jetbrains.kotlin.plugin.parcelize": ("parcelize", "serialization"),
    "kotlin-parcelize": ("parcelize", "serialization"),
    "androidx.navigation.safeargs": ("navigation_safeargs", "navigation"),
    "androidx.navigation.safeargs.kotlin": ("navigation_safeargs", "navigation"),
    "com.google.gms.google-services": ("google_services", "firebase"),
    "com.google.firebase.crashlytics": ("crashlytics", "firebase"),
}

# Import prefixes -> (technology, category); the longest matching prefix wins.
IMPORT_TECH: tuple[tuple[str, str, str], ...] = (
    ("androidx.compose.", "compose", "ui"),
    ("androidx.navigation.compose.", "navigation_compose", "navigation"),
    ("androidx.navigation.fragment.", "navigation_fragment", "navigation"),
    ("androidx.navigation.", "navigation", "navigation"),
    ("androidx.navigation3.", "navigation3", "navigation"),
    ("androidx.appcompat.", "appcompat", "ui"),
    ("com.google.android.material.", "material_components", "ui"),
    ("androidx.recyclerview.", "recyclerview", "ui"),
    ("androidx.fragment.", "fragment", "ui"),
    ("androidx.room.", "room", "storage"),
    ("android.arch.persistence.room.", "room", "storage"),
    ("androidx.datastore.", "datastore", "storage"),
    ("androidx.preference.", "preferences", "storage"),
    ("android.content.SharedPreferences", "shared_preferences", "storage"),
    ("android.database.sqlite.", "sqlite", "storage"),
    ("io.realm.", "realm", "storage"),
    ("io.objectbox.", "objectbox", "storage"),
    ("app.cash.sqldelight.", "sqldelight", "storage"),
    ("com.google.firebase.firestore.", "firestore", "storage"),
    ("com.google.firebase.database.", "firebase_realtime_database", "storage"),
    ("androidx.security.crypto.", "encrypted_storage", "storage"),
    ("retrofit2.converter.", "retrofit_converter", "network"),
    ("retrofit2.", "retrofit", "network"),
    ("okhttp3.", "okhttp", "network"),
    ("io.ktor.client.", "ktor_client", "network"),
    ("com.android.volley.", "volley", "network"),
    ("java.net.HttpURLConnection", "http_url_connection", "network"),
    ("android.webkit.WebView", "webview", "network"),
    ("com.google.gson.", "gson", "serialization"),
    ("com.squareup.moshi.", "moshi", "serialization"),
    ("kotlinx.serialization.", "kotlinx_serialization", "serialization"),
    ("dagger.hilt.", "hilt", "di"),
    ("androidx.hilt.", "hilt", "di"),
    ("dagger.", "dagger", "di"),
    ("org.koin.", "koin", "di"),
    ("org.kodein.", "kodein", "di"),
    ("androidx.lifecycle.ViewModel", "viewmodel", "architecture"),
    ("androidx.lifecycle.AndroidViewModel", "viewmodel", "architecture"),
    ("androidx.lifecycle.viewmodel.", "viewmodel", "architecture"),
    ("androidx.lifecycle.LiveData", "livedata", "architecture"),
    ("androidx.lifecycle.MutableLiveData", "livedata", "architecture"),
    ("androidx.lifecycle.", "lifecycle", "architecture"),
    ("androidx.work.", "workmanager", "architecture"),
    ("androidx.paging.", "paging", "architecture"),
    ("kotlinx.coroutines.flow.", "kotlin_flow", "async"),
    ("kotlinx.coroutines.", "coroutines", "async"),
    ("io.reactivex.", "rxjava", "async"),
    ("coil.", "coil", "image"),
    ("coil3.", "coil", "image"),
    ("com.bumptech.glide.", "glide", "image"),
    ("com.squareup.picasso.", "picasso", "image"),
    ("com.google.firebase.auth.", "firebase_auth", "firebase"),
    ("com.google.firebase.messaging.", "firebase_messaging", "firebase"),
    ("com.google.firebase.", "firebase", "firebase"),
)


def longest_prefix(table: tuple[tuple[str, str, str], ...], text: str) -> tuple[str, str] | None:
    """``(technology, category)`` of the longest prefix in ``table`` that ``text`` starts with."""
    best: tuple[int, str, str] | None = None
    for prefix, tech, category in table:
        if text.startswith(prefix) and (best is None or len(prefix) > best[0]):
            best = (len(prefix), tech, category)
    return (best[1], best[2]) if best else None


TEST_CONFIG_PREFIXES = (
    "test",
    "androidTest",
    "kaptTest",
    "kaptAndroidTest",
    "kspTest",
    "kspAndroidTest",
)


def is_test_config(config: str) -> bool:
    return config.startswith(TEST_CONFIG_PREFIXES)
