from flask import Flask, request, render_template, session, redirect, url_for
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
import markdown
from datetime import datetime
from flask_migrate import Migrate
from slugify import slugify
from sqlalchemy import func, desc
from flask import flash
import uuid
from dotenv import load_dotenv
import os

app = Flask(__name__)
load_dotenv()
database_url = os.getenv("DATABASE_URL")
app.config["SQLALCHEMY_DATABASE_URI"] = database_url
app.config["SECRET_KEY"] = "spezsucks453789"  # replace this with a real secret key
db = SQLAlchemy(app)

engine = db.create_engine(database_url)

# Define the association table for the many-to-many relationship between Users and Communities
community_members = db.Table(
    "community_members",
    db.Column("user_id", db.Integer, db.ForeignKey("user.id"), primary_key=True),
    db.Column(
        "community_id", db.Integer, db.ForeignKey("community.id"), primary_key=True
    ),
)
migrate = Migrate(app, db)


class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password = db.Column(db.String(120), nullable=False)
    posts = db.relationship("Post", backref="author", lazy=True)
    communities = db.relationship(
        "Community",
        secondary=community_members,
        backref=db.backref("members", lazy="dynamic"),
    )


class Post(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(120), nullable=False)
    content = db.Column(db.Text, nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    community_id = db.Column(db.Integer, db.ForeignKey("community.id"), nullable=False)
    upvotes = db.Column(db.Integer, default=0)
    downvotes = db.Column(db.Integer, default=0)
    comments = db.relationship("Comment", backref="post", lazy=True)
    slug = db.Column(db.String(120), nullable=False)

    @property
    def score(self):
        return self.upvotes - self.downvotes


class Comment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    content = db.Column(db.Text, nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    post_id = db.Column(db.Integer, db.ForeignKey("post.id"), nullable=False)
    author = db.relationship("User", backref=db.backref("comments", lazy=True))


class Community(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(80), unique=True, nullable=False)
    description = db.Column(db.String(200))
    creator_id = db.Column(db.Integer, db.ForeignKey("user.id"))
    creator = db.relationship(
        "User", backref=db.backref("created_communities", lazy=True)
    )
    posts = db.relationship("Post", backref="community", lazy=True)


class Vote(db.Model):
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), primary_key=True)
    post_id = db.Column(db.Integer, db.ForeignKey("post.id"), primary_key=True)
    vote_value = db.Column(db.Integer)


@app.route("/")
def index():
    posts = Post.query.all()
    top_communities = (
        Community.query.join(Community.posts)
        .with_entities(Community, func.count(Post.id).label("post_count"))
        .group_by(Community)
        .order_by(func.count(Post.id).desc())
        .limit(5)
        .all()
    )
    # Default community when you're at the index page
    community = (
        Community.query.first()
    )  # or however you want to get a default community
    default_community_id = Community.query.filter_by(name="effit").first().id
    return render_template(
        "index.html",
        posts=posts,
        top_communities=top_communities,
        community=community,
        default_community_id=default_community_id,
    )


@app.route("/post", methods=["POST"])
def post():
    if "username" not in session:
        return "You must be logged in to post!", 401
    title = request.form.get("title")
    slug = slugify(title)
    content = request.form.get("content")
    community_id = request.form.get("community_id")
    if community_id is None:
        community = Community.query.filter_by(name="effit").first()
        community_id = community.id if community else None
    user = User.query.filter_by(username=session["username"]).first()
    post = Post(
        title=title,
        slug=f"{slugify(title)}-{str(uuid.uuid4())[:8]}",
        content=content,
        user_id=user.id,
        community_id=community_id,
    )
    db.session.add(post)
    db.session.commit()

    # Retrieve the community associated with the post
    community = Community.query.filter_by(id=community_id).first()

    return render_template("post_detail.html", post=post, community=community)


@app.route("/post/<int:post_id>/comment", methods=["POST"])
def add_comment(post_id):
    if "username" not in session:
        return "You must be logged in to comment!", 401
    content = request.form.get("content")
    user = User.query.filter_by(username=session["username"]).first()
    comment = Comment(content=content, user_id=user.id, post_id=post_id)
    db.session.add(comment)
    db.session.commit()
    post = Post.query.get(post_id)
    return redirect(
        url_for("post_detail", community_name=post.community.name, post_slug=post.slug)
    )


@app.route("/c/<string:community_name>/p/<string:post_slug>", methods=["GET", "POST"])
def post_detail(community_name, post_slug):
    post = Post.query.filter_by(slug=post_slug).first()
    if post is None:
        return "Post not found!", 404

    if request.method == "POST":
        action = request.form.get("action")

        if action == "delete":
            db.session.delete(post)
            db.session.commit()
            return redirect(url_for("community_posts", community_name=community_name))

        if action == "edit":
            title = request.form.get("title")
            content = request.form.get("content")
            post.title = title
            post.content = content
            db.session.commit()

    comments = Comment.query.filter_by(post_id=post.id).all()
    post.content = markdown.markdown(post.content)
    for comment in comments:
        comment.content = markdown.markdown(comment.content)

    community = Community.query.filter_by(name=community_name).first()
    if community is None:
        return "Community not found!", 404

    return render_template(
        "post_detail.html", post=post, comments=comments, community=community
    )


@app.route("/post/<int:post_id>/edit", methods=["GET", "POST"])
def edit_post(post_id):
    if "username" not in session:
        return "You must be logged in to edit a post!", 401

    post = Post.query.get(post_id)

    # Check if the post exists and the logged-in user is the author
    if post is None or post.author.username != session["username"]:
        return "Post not found or you are not authorized to edit it!", 404

    if request.method == "POST":
        # Update the post content with the submitted form data
        post.title = request.form.get("title")
        post.content = request.form.get("content")
        db.session.commit()
        return redirect(
            url_for(
                "post_detail", community_name=post.community.name, post_slug=post.slug
            )
        )

    return render_template("edit_post.html", post=post)


@app.route("/post/<int:post_id>/delete", methods=["POST"])
def delete_post(post_id):
    if "username" not in session:
        return "You must be logged in to delete a post!", 401

    post = Post.query.get(post_id)

    # Check if the post exists and the logged-in user is the author
    if post is None or post.author.username != session["username"]:
        return "Post not found or you are not authorized to delete it!", 404

    # Delete the comments associated with the post
    Comment.query.filter_by(post_id=post_id).delete()

    # Delete the post
    db.session.delete(post)
    db.session.commit()

    return redirect(url_for("index"))


@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        username = request.form.get("username")
        password = request.form.get("password")

        # Check if a user with the same username already exists
        existing_user = User.query.filter_by(username=username).first()
        if existing_user:
            flash(
                "Username already exists. Please choose a different username.", "error"
            )
            return redirect(url_for("register"))

        # Create a new user and add it to the database
        password_hash = generate_password_hash(password)
        user = User(username=username, password=password_hash)
        db.session.add(user)
        db.session.commit()
        flash("Registration successful. You can now log in.", "success")
        return redirect(url_for("login"))

    return render_template("register.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username")
        password = request.form.get("password")
        user = User.query.filter_by(username=username).first()
        if user is None or not check_password_hash(user.password, password):
            return "Invalid username or password", 401
        session["username"] = username
        return redirect(url_for("index"))
    return render_template("login.html")


@app.route("/create_community", methods=["GET", "POST"])
def create_community():
    if "username" not in session:
        return "You must be logged in to create a community!", 401
    if request.method == "POST":
        name = request.form.get("name")
        description = request.form.get("description")
        user = User.query.filter_by(username=session["username"]).first()
        community = Community(name=name, description=description, creator=user)
        community.members.append(user)
        db.session.add(community)
        db.session.commit()
        return redirect(url_for("index"))
    return render_template("create_community.html")


@app.route("/logout")
def logout():
    session.pop("username", None)
    return redirect(url_for("index"))


@app.route("/c/<string:community_name>")
def community_posts(community_name):
    community = Community.query.filter_by(name=community_name).first()
    if community is None:
        return "Community not found!", 404
    posts = Post.query.filter_by(community_id=community.id).all()
    return render_template("community_posts.html", community=community, posts=posts)


@app.route("/e/<string:community_slug>/join", methods=["POST"])
def join_community(community_slug):
    if "username" not in session:
        return "You must be logged in to join a community!", 401
    community = Community.query.filter_by(slug=community_slug).first()
    if community is None:
        return "Community not found!", 404
    user = User.query.filter_by(username=session["username"]).first()
    community.members.append(user)
    db.session.commit()
    return redirect(url_for("community_detail", community_slug=community_slug))


@app.route("/post/<string:community_name>/<string:post_slug>/upvote", methods=["POST"])
def upvote_post(community_name, post_slug):
    if "username" not in session:
        return "You must be logged in to vote!", 401
    post = Post.query.filter_by(slug=post_slug).first()
    user = User.query.filter_by(username=session["username"]).first()
    vote = Vote.query.filter_by(user_id=user.id, post_id=post.id).first()
    if vote is None:
        vote = Vote(user_id=user.id, post_id=post.id, vote_value=1)
        db.session.add(vote)
    else:
        vote.vote_value = 0 if vote.vote_value == 1 else 1
    db.session.commit()
    return redirect(
        url_for("post_detail", community_name=community_name, post_slug=post_slug)
    )


@app.route(
    "/post/<string:community_name>/<string:post_slug>/downvote", methods=["POST"]
)
def downvote_post(community_name, post_slug):
    if "username" not in session:
        return "You must be logged in to vote!", 401
    post = Post.query.filter_by(slug=post_slug).first()
    user = User.query.filter_by(username=session["username"]).first()
    vote = Vote.query.filter_by(user_id=user.id, post_id=post.id).first()
    if vote is None:
        vote = Vote(user_id=user.id, post_id=post.id, vote_value=-1)
        db.session.add(vote)
    else:
        vote.vote_value = 0 if vote.vote_value == -1 else -1
    db.session.commit()
    return redirect(
        url_for("post_detail", community_name=community_name, post_slug=post_slug)
    )


@app.route("/user/<string:username>/posts")
def user_posts(username):
    user = User.query.filter_by(username=username).first_or_404()
    posts = Post.query.filter_by(user_id=user.id).all()
    return render_template("user_posts.html", posts=posts, user=user)


if __name__ == "__main__":
    with app.app_context():
        db.create_all()
        effit_community = Community.query.filter_by(name="effit").first()
        if effit_community is None:
            effit_community = Community(name="effit", description="Default community")
            db.session.add(effit_community)
            db.session.commit()
    app.run(host="0.0.0.0", port=5000, debug=True)
