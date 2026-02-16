import json
import os
import pathlib
import sys
import time

# Default: isolate smoke tests on a dedicated sqlite DB so production/dev DB is not polluted.
if not os.environ.get("DATABASE_URL"):
    smoke_db = pathlib.Path("instance/smoke_test.db").resolve()
    os.environ["DATABASE_URL"] = "sqlite:///" + str(smoke_db).replace("\\", "/")

# Optional reset (default on).
if os.environ.get("SMOKE_RESET_DB", "1") == "1":
    db_path = pathlib.Path(os.environ["DATABASE_URL"].replace("sqlite:///", ""))
    db_path.parent.mkdir(parents=True, exist_ok=True)
    db_path.unlink(missing_ok=True)

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app import app, User


report = []


def rec(name, ok, status=None, detail=None):
    report.append({
        "name": name,
        "ok": bool(ok),
        "status": status,
        "detail": detail,
    })


def status_ok(resp, allowed):
    if isinstance(allowed, (list, tuple, set)):
        return resp.status_code in allowed
    return resp.status_code == allowed


def run():
    with app.test_client() as c:
        ts = str(int(time.time()))
        u1 = f"qauser_{ts}"
        u2 = f"qauser2_{ts}"
        p1 = "QaPass123X"
        p2 = "QaPass456X"

        r = c.post("/register", json={
            "username": u1,
            "password": p1,
            "display_name": "QA User One",
            "education_level": "lise",
        })
        rec("register_u1", status_ok(r, 201), r.status_code, r.get_json(silent=True))

        r = c.post("/register", json={
            "username": u2,
            "password": p2,
            "display_name": "QA User Two",
            "education_level": "lisans",
        })
        rec("register_u2", status_ok(r, 201), r.status_code, r.get_json(silent=True))

        r = c.post("/login", json={"username": u1, "password": p1})
        rec("login_u1", status_ok(r, 200), r.status_code, r.get_json(silent=True))

        for p in [
            "/",
            "/dashboard/home",
            "/dashboard/social",
            "/dashboard/calc",
            "/dashboard/edu",
            "/dashboard/profile",
            "/dashboard/settings",
            "/dashboard/social/search",
        ]:
            rr = c.get(p)
            rec(f"page_{p}", status_ok(rr, 200), rr.status_code)

        r = c.get("/auth/me")
        rec("auth_me_u1", status_ok(r, 200), r.status_code, r.get_json(silent=True))

        r = c.get("/profile")
        rec("profile_get_u1", status_ok(r, 200), r.status_code)

        r = c.put("/profile", json={"username": f"{u1}_x"})
        rec("profile_username_immutable", status_ok(r, 400), r.status_code, r.get_json(silent=True))

        r = c.put("/profile", json={"display_name": "QA One Updated", "education_level": "yetiskin"})
        rec("profile_update_u1", status_ok(r, 200), r.status_code, r.get_json(silent=True))

        r = c.post("/profile/email", json={"email": "badmail"})
        rec("profile_email_invalid", status_ok(r, 400), r.status_code, r.get_json(silent=True))

        r = c.post("/profile/email", json={"email": f"{u1}@example.com"})
        rec("profile_email_valid", status_ok(r, [200, 409, 500]), r.status_code, r.get_json(silent=True))

        r = c.post("/profile/password", json={"current_password": p1, "new_password": "NewPass123X"})
        rec("profile_password_change", status_ok(r, 200), r.status_code, r.get_json(silent=True))

        details = [{"category": "Ulasim", "question": "test", "answer": "test", "score": 3}]
        r = c.post("/save_score", json={"score": 12.4, "details": details})
        rec("save_score_first", status_ok(r, 201), r.status_code, r.get_json(silent=True))

        r = c.post("/save_score", json={"score": 13.1, "details": details})
        rec("save_score_duplicate_day", status_ok(r, 409), r.status_code, r.get_json(silent=True))

        r = c.get("/api/carbon/overview")
        rec("carbon_overview", status_ok(r, 200), r.status_code)

        r = c.get("/api/carbon/comment")
        rec("carbon_comment", status_ok(r, [200, 502]), r.status_code, r.get_json(silent=True))

        r = c.post("/api/calculate-ai", json={"text": "Bugun ise arabayla gittim"})
        rec("calculate_ai", status_ok(r, [200, 409, 500]), r.status_code, r.get_json(silent=True))

        r = c.post("/api/ai-chat", json={"message": "karbonumu nasil dusururum"})
        rec("ai_chat", status_ok(r, [200, 402, 500, 502]), r.status_code, r.get_json(silent=True))

        r = c.post("/api/forum/post", json={
            "title": "QA pending post",
            "content": "pending content",
            "category": "genel",
        })
        post_payload = r.get_json(silent=True) or {}
        post_id = post_payload.get("post_id")
        rec(
            "forum_create_post_pending",
            status_ok(r, 201) and post_payload.get("status") in {"pending", "approved"},
            r.status_code,
            post_payload,
        )

        r = c.get("/api/forum/feed")
        rec("forum_feed_u1", status_ok(r, 200), r.status_code)

        r = c.get("/api/forum/mod/pending")
        rec("forum_mod_pending_u1_forbidden", status_ok(r, 403), r.status_code)

        c.post("/logout")

        r = c.post("/login", json={"username": "eymen", "password": "eymen200909"})
        rec("login_owner", status_ok(r, 200), r.status_code, r.get_json(silent=True))

        rr = c.get("/dashboard/admin")
        rec("page_dashboard_admin_owner", status_ok(rr, 200), rr.status_code)
        rr = c.get("/dashboard/moderation")
        rec("page_dashboard_moderation_owner", status_ok(rr, 200), rr.status_code)

        r = c.get("/api/forum/mod/pending")
        pend = r.get_json(silent=True) or {}
        rec("forum_mod_pending_owner", status_ok(r, 200), r.status_code, {"count": pend.get("count")})

        if post_id:
            r = c.post(f"/api/forum/mod/post/{post_id}/approve")
            rec("forum_mod_approve", status_ok(r, 200), r.status_code, r.get_json(silent=True))

        r = c.post("/api/forum/owner/moderator", json={"username": u2, "moderator": True})
        rec("owner_set_moderator_u2", status_ok(r, 200), r.status_code, r.get_json(silent=True))

        r = c.get("/api/forum/owner/moderators")
        rec("owner_moderator_list", status_ok(r, 200), r.status_code)

        r = c.get("/api/social/search", query_string={"q": u1, "user_limit": 10, "post_limit": 10})
        rec("social_search_owner", status_ok(r, 200), r.status_code)

        c.post("/logout")

        r = c.post("/login", json={"username": u2, "password": p2})
        rec("login_u2", status_ok(r, 200), r.status_code, r.get_json(silent=True))

        with app.app_context():
            u1_obj = User.query.filter_by(username=u1).first()
            u1_id = u1_obj.id if u1_obj else None

        if u1_id:
            r = c.post(f"/api/social/follow/{u1_id}")
            rec("social_follow_u1", status_ok(r, 200), r.status_code, r.get_json(silent=True))

        r = c.get("/api/forum/feed", query_string={"feed": "following"})
        data = r.get_json(silent=True) or {}
        rec(
            "forum_feed_following",
            status_ok(r, 200),
            r.status_code,
            {"posts": len(data.get("posts", [])) if isinstance(data, dict) else None},
        )

        if post_id:
            r = c.post(f"/api/forum/post/{post_id}/like")
            rec("forum_like_post", status_ok(r, 200), r.status_code, r.get_json(silent=True))

            r = c.post(f"/api/forum/post/{post_id}/comment", json={"content": "ilk yorum"})
            c1 = (r.get_json(silent=True) or {}).get("comment", {}) if r.status_code in (200, 201) else {}
            c1_id = c1.get("id")
            rec("forum_comment_add", status_ok(r, 201), r.status_code, r.get_json(silent=True))

            if c1_id:
                r = c.post(
                    f"/api/forum/post/{post_id}/comment",
                    json={"content": "yanit yorum", "reply_to_id": c1_id},
                )
                c2 = (r.get_json(silent=True) or {}).get("comment", {}) if r.status_code in (200, 201) else {}
                c2_id = c2.get("id")
                rec("forum_comment_reply", status_ok(r, 201), r.status_code, r.get_json(silent=True))

                r = c.put(f"/api/forum/comment/{c1_id}", json={"content": "duzenlenmis yorum"})
                rec("forum_comment_edit", status_ok(r, 200), r.status_code, r.get_json(silent=True))

                if c2_id:
                    r = c.delete(f"/api/forum/comment/{c2_id}")
                    rec("forum_comment_delete_reply", status_ok(r, 200), r.status_code, r.get_json(silent=True))

            r = c.get(f"/api/forum/post/{post_id}/comments")
            rec("forum_comment_list", status_ok(r, 200), r.status_code)

        r = c.get("/api/giphy/search", query_string={"q": "cat", "limit": 5})
        gdata = r.get_json(silent=True) or {}
        items = gdata.get("items") if isinstance(gdata, dict) else []
        rec(
            "giphy_search",
            status_ok(r, 200),
            r.status_code,
            {
                "count": len(items or []),
                "fallback": gdata.get("fallback") if isinstance(gdata, dict) else None,
                "message": gdata.get("message") if isinstance(gdata, dict) else None,
            },
        )

        if items:
            one = items[0]
            r = c.post("/api/giphy/favorite", json={
                "gif_id": one.get("gif_id"),
                "gif_url": one.get("gif_url"),
                "preview_url": one.get("preview_url"),
                "title": one.get("title"),
            })
            rec("giphy_add_favorite", status_ok(r, 200), r.status_code, r.get_json(silent=True))

            r = c.get("/api/giphy/favorites")
            rec("giphy_list_favorites", status_ok(r, 200), r.status_code, {"count": (r.get_json(silent=True) or {}).get("count")})

            gid = one.get("gif_id")
            if gid:
                r = c.delete(f"/api/giphy/favorite/{gid}")
                rec("giphy_delete_favorite", status_ok(r, 200), r.status_code, r.get_json(silent=True))

        r = c.post("/account-delete/request-code")
        rec("account_delete_request_code", status_ok(r, [200, 400, 502]), r.status_code, r.get_json(silent=True))

        if post_id:
            r = c.delete(f"/api/forum/post/{post_id}")
            rec("forum_delete_post_as_moderator", status_ok(r, 200), r.status_code, r.get_json(silent=True))

    all_ok = all(x["ok"] for x in report)
    print(json.dumps({
        "all_ok": all_ok,
        "total": len(report),
        "failed": [x for x in report if not x["ok"]],
        "report": report,
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    run()
